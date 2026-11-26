"""Повторяющиеся напоминания: расписание и разворачивание в задачи на 60 дней вперёд."""

from collections.abc import Iterator
from datetime import date, timedelta
from itertools import count
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Company,
    RecurringReminder,
    ShiftRule,
    Task,
    TaskKind,
    TaskSource,
    TaskStatus,
    User,
)
from app.services.calendar.workdays import WorkCalendar
from app.services.rules.engine import add_months, day_of_month
from app.services.task_state import is_untouched

HORIZON = timedelta(days=60)
MONTH_STEPS = {"monthly": 1, "quarterly": 3, "yearly": 12}


class Schedule(BaseModel):
    """Расписание в терминах формы. В базе хранится строкой RRULE (RFC 5545)."""

    model_config = ConfigDict(extra="forbid")

    frequency: Literal["monthly", "quarterly", "yearly", "weekly"]
    # для месячных расписаний; если такого числа в месяце нет — последний день
    day_of_month: int | None = Field(None, ge=1, le=31)
    interval_weeks: int | None = Field(None, ge=1, le=52)

    @model_validator(mode="after")
    def consistent(self) -> "Schedule":
        if self.frequency == "weekly":
            if self.interval_weeks is None:
                raise ValueError("укажите, раз во сколько недель")
            self.day_of_month = None
        else:
            if self.day_of_month is None:
                raise ValueError("укажите число месяца")
            self.interval_weeks = None
        return self

    def to_rrule(self) -> str:
        if self.frequency == "weekly":
            return f"FREQ=WEEKLY;INTERVAL={self.interval_weeks}"
        if self.frequency == "yearly":
            return f"FREQ=YEARLY;INTERVAL=1;BYMONTHDAY={self.day_of_month}"
        step = MONTH_STEPS[self.frequency]
        return f"FREQ=MONTHLY;INTERVAL={step};BYMONTHDAY={self.day_of_month}"

    @classmethod
    def from_rrule(cls, rrule: str) -> "Schedule":
        parts = dict(item.split("=", 1) for item in rrule.split(";"))
        interval = int(parts.get("INTERVAL", 1))
        if parts["FREQ"] == "WEEKLY":
            return cls(frequency="weekly", interval_weeks=interval)
        if parts["FREQ"] == "YEARLY":
            frequency = "yearly"
        else:
            frequency = {1: "monthly", 3: "quarterly"}[interval]
        return cls(frequency=frequency, day_of_month=int(parts["BYMONTHDAY"]))


def _all_dates(schedule: Schedule, start: date) -> Iterator[date]:
    for number in count():
        if schedule.frequency == "weekly":
            yield start + timedelta(weeks=number * schedule.interval_weeks)
        else:
            step = MONTH_STEPS[schedule.frequency]
            year, month = add_months(start.year, start.month, number * step)
            yield day_of_month(year, month, schedule.day_of_month)


def occurrence_dates(
    schedule: Schedule, start: date, until: date | None, date_from: date, date_to: date
) -> Iterator[date]:
    """Даты расписания в интервале, не раньше начала и не позже окончания."""
    last = min(date_to, until) if until else date_to
    for day in _all_dates(schedule, start):
        if day > last:
            return
        if day >= max(start, date_from):
            yield day


def shift(day: date, rule: str, work_calendar: WorkCalendar) -> date:
    if rule == ShiftRule.NONE:
        return day
    step = timedelta(days=1 if rule == ShiftRule.NEXT_WORKDAY else -1)
    while not work_calendar.is_workday(day):
        day += step
    return day


async def _is_live(db: AsyncSession, reminder: RecurringReminder) -> bool:
    if not reminder.is_active:
        return False
    if reminder.company_id is not None:
        company = await db.get(Company, reminder.company_id)
        return company is not None and not company.is_archived
    owner = await db.get(User, reminder.created_by)
    return owner is not None and owner.is_active


async def _instances(db: AsyncSession, reminder_id: int) -> list[Task]:
    return list(await db.scalars(select(Task).where(Task.recurring_reminder_id == reminder_id)))


async def expand(
    db: AsyncSession, reminder: RecurringReminder, work_calendar: WorkCalendar, current: date
) -> int:
    """Создаёт недостающие задачи. Транзакцию фиксирует вызывающий."""
    # Блокировка: воркер и API не развернут одно напоминание одновременно.
    await db.refresh(reminder, with_for_update=True)
    if not await _is_live(db, reminder):
        return 0
    existing = {task.period_key: task for task in await _instances(db, reminder.id)}
    # перенос мог измениться после загрузки производственного календаря
    for task in existing.values():
        if task.status == TaskStatus.PLANNED and not task.due_overridden:
            if task.original_due_date >= current:
                task.due_date = shift(task.original_due_date, reminder.shift_rule, work_calendar)
    created = 0
    dates = occurrence_dates(
        Schedule.from_rrule(reminder.rrule),
        reminder.dtstart,
        reminder.until,
        current,
        current + HORIZON,
    )
    for day in dates:
        if day.isoformat() in existing:
            continue
        db.add(
            Task(
                company_id=reminder.company_id,
                owner_id=None if reminder.company_id else reminder.created_by,
                recurring_reminder_id=reminder.id,
                source=TaskSource.CUSTOM,
                period_key=day.isoformat(),
                kind=reminder.kind,
                title=reminder.title,
                description=reminder.description,
                due_date=shift(day, reminder.shift_rule, work_calendar),
                original_due_date=day,
                needs_amount=reminder.kind == TaskKind.PAYMENT,
                client_visible=reminder.client_visible,
                status=TaskStatus.PLANNED,
            )
        )
        created += 1
    await db.flush()
    return created


async def expand_where(
    db: AsyncSession, work_calendar: WorkCalendar, current: date, company_id: int | None = None
) -> int:
    """Все напоминания или напоминания одной компании."""
    query = select(RecurringReminder).where(RecurringReminder.is_active.is_(True))
    if company_id is not None:
        query = query.where(RecurringReminder.company_id == company_id)
    created = 0
    for reminder in list(await db.scalars(query.order_by(RecurringReminder.id))):
        created += await expand(db, reminder, work_calendar, current)
    return created


async def drop_future(db: AsyncSession, reminder: RecurringReminder, current: date) -> None:
    """Удаляет будущие задачи напоминания, которые никто не менял."""
    for task in await _instances(db, reminder.id):
        if task.original_due_date >= current and is_untouched(task):
            await db.delete(task)
    await db.flush()
