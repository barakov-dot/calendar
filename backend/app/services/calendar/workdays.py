"""Производственный календарь и перенос сроков.

п. 7 ст. 6.1 НК РФ: если последний день срока — выходной или нерабочий праздничный,
сроком считается ближайший следующий за ним рабочий день.
"""

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WorkDay


class CalendarError(Exception):
    pass


class CalendarFile(BaseModel):
    """data/calendar/<год>.json: отличия от обычной пятидневки."""

    model_config = ConfigDict(extra="forbid")

    year: int = Field(ge=2020, le=2100)
    source: str = Field(min_length=1, max_length=255)
    days_off: list[date] = Field(max_length=100)
    working_weekends: list[date] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def consistent(self) -> "CalendarFile":
        for day in self.days_off + self.working_weekends:
            if day.year != self.year:
                raise ValueError(f"дата {day} не относится к {self.year} году")
        if wrong := [day for day in self.days_off if day.weekday() >= 5]:
            raise ValueError(f"в days_off перечисляют только будни, а {wrong[0]} — выходной")
        if wrong := [day for day in self.working_weekends if day.weekday() < 5]:
            raise ValueError(f"в working_weekends — только субботы и воскресенья: {wrong[0]}")
        return self

    def days(self) -> dict[date, bool]:
        """Все даты года и признак рабочего дня."""
        off, working = set(self.days_off), set(self.working_weekends)
        result = {}
        day = date(self.year, 1, 1)
        while day.year == self.year:
            result[day] = day in working or (day.weekday() < 5 and day not in off)
            day += timedelta(days=1)
        return result


def parse_calendar(data: Any) -> CalendarFile:
    try:
        return CalendarFile.model_validate(data)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(map(str, item['loc'])) or 'файл'}: "
            f"{item['msg'].removeprefix('Value error, ')}"
            for item in error.errors(include_input=False, include_url=False)
        )
        raise CalendarError(problems) from None


def read_calendar_file(path: Path) -> CalendarFile:
    try:
        return CalendarFile.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as error:
        raise CalendarError(f"{path.name}: {error}") from None


class WorkCalendar:
    """Если года нет в календаре, рабочими считаются понедельник–пятница."""

    def __init__(self, days: dict[date, bool]) -> None:
        self._days = days
        self.years = {day.year for day in days}
        # годы, для которых пришлось обойтись без календаря
        self.missing_years: set[int] = set()

    def is_workday(self, day: date) -> bool:
        if day.year not in self.years:
            self.missing_years.add(day.year)
            return day.weekday() < 5
        return self._days[day]

    def shift_to_workday(self, day: date) -> date:
        """Ближайший рабочий день, начиная с day (вперёд)."""
        while not self.is_workday(day):
            day += timedelta(days=1)
        return day

    def last_workday_of_year(self, year: int) -> date:
        day = date(year, 12, 31)
        while not self.is_workday(day):
            day -= timedelta(days=1)
        return day


async def load_calendar(db: AsyncSession) -> WorkCalendar:
    rows = await db.execute(select(WorkDay.date, WorkDay.is_workday))
    return WorkCalendar({day: is_workday for day, is_workday in rows})


async def save_year(db: AsyncSession, calendar: CalendarFile) -> None:
    """Заменяет год целиком. Транзакцию фиксирует вызывающий."""
    await db.execute(
        delete(WorkDay).where(
            WorkDay.date.between(date(calendar.year, 1, 1), date(calendar.year, 12, 31))
        )
    )
    db.add_all(
        WorkDay(date=day, is_workday=is_workday, note=calendar.source)
        for day, is_workday in calendar.days().items()
    )
    await db.flush()


async def loaded_years(db: AsyncSession) -> list[dict]:
    year = func.extract("year", WorkDay.date)
    rows = await db.execute(
        select(
            year,
            func.count().filter(WorkDay.is_workday),
            func.count(),
            func.max(WorkDay.note),
        )
        .group_by(year)
        .order_by(year)
    )
    return [
        {"year": int(y), "workdays": workdays, "days_off": total - workdays, "source": note}
        for y, workdays, total, note in rows
    ]


async def load_missing_years(db: AsyncSession, directory: Path) -> list[int]:
    """Загружает из data/calendar годы, которых ещё нет в базе."""
    present = {item["year"] for item in await loaded_years(db)}
    added = []
    # несколько локальных файлов при запуске: блокировка цикла несущественна
    for path in sorted(directory.glob("[0-9][0-9][0-9][0-9].json")):  # noqa: ASYNC240
        if int(path.stem) in present:
            continue
        calendar = read_calendar_file(path)
        await save_year(db, calendar)
        added.append(calendar.year)
    await db.commit()
    return added
