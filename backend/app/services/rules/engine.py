"""Движок налоговых правил: из данных компании и rules/<год>.yaml получает сроки.

Файл rules/<год>.yaml описывает налоговые периоды этого года (и более ранние, если
отдельного файла для них нет). Для лет без файла сроки не создаются: изменения
законодательства нельзя угадывать.
"""

import calendar as month_calendar
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Protocol

import yaml
from pydantic import ValidationError

from app.services.calendar.workdays import WorkCalendar
from app.services.rules.schema import (
    Handler,
    Monthly,
    NdsThirds,
    Quarterly,
    Rule,
    RuleFile,
    Yearly,
)

MONTHS = "январь февраль март апрель май июнь июль август сентябрь октябрь ноябрь декабрь".split()
MONTHS_GENITIVE = (
    "января февраля марта апреля мая июня июля августа сентября октября ноября декабря".split()
)
QUARTER_NAMES = ("I квартал", "II квартал", "III квартал", "IV квартал")
CUMULATIVE_NAMES = ("I квартал", "полугодие", "9 месяцев", "год")  # «год» → «2026 год»


class RulesError(Exception):
    pass


class PatentLike(Protocol):
    id: int
    number: str
    date_start: date
    date_end: date
    cost_kopecks: int | None


@dataclass(frozen=True)
class Occurrence:
    """Один срок по правилу для конкретной компании."""

    rule_code: str
    period_key: str
    period_year: int
    part: int
    kind: str
    title: str
    description: str
    source_ref: str
    original_due_date: date
    due_date: date
    needs_amount: bool
    client_visible: bool
    amount_kopecks: int | None = None


class RuleBook:
    def __init__(self, files: Iterable[RuleFile]) -> None:
        self._files = {file.year: file for file in files}
        if not self._files:
            raise RulesError("нет ни одного файла правил")

    @property
    def years(self) -> list[int]:
        return sorted(self._files)

    @property
    def latest_year(self) -> int:
        return max(self._files)

    def for_period_year(self, year: int) -> RuleFile | None:
        if year in self._files:
            return self._files[year]
        # Периоды до первого файла (например, декларации за прошлый год)
        return self._files[min(self._files)] if year < min(self._files) else None


def load_rules(directory: Path) -> RuleBook:
    files = []
    for path in sorted(directory.glob("[0-9][0-9][0-9][0-9].yaml")):
        try:
            file = RuleFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        except (OSError, yaml.YAMLError, ValidationError) as error:
            raise RulesError(f"{path.name}: {error}") from None
        if file.year != int(path.stem):
            raise RulesError(f"{path.name}: внутри указан год {file.year}")
        files.append(file)
    return RuleBook(files)


def add_months(year: int, month: int, offset: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + offset
    return index // 12, index % 12 + 1


def day_of_month(year: int, month: int, day: int) -> date:
    """п. 5 ст. 6.1 НК РФ: если такого числа в месяце нет — последний день месяца."""
    return date(year, month, min(day, month_calendar.monthrange(year, month)[1]))


@dataclass(frozen=True)
class _Draft:
    period_key: str
    due: date
    part: int = 1
    names: tuple[tuple[str, str], ...] = ()
    amount: int | None = None
    note: str = ""


def _monthly(schedule: Monthly, year: int) -> Iterator[_Draft]:
    for month in schedule.months:
        due = day_of_month(*add_months(year, month, schedule.month_offset), schedule.day)
        names = (
            ("period_name", f"{MONTHS[month - 1]} {year}"),
            ("month_genitive", MONTHS_GENITIVE[month - 1]),
        )
        yield _Draft(f"{year}-{month:02d}", due, names=names)


def _quarterly(schedule: Quarterly, year: int) -> Iterator[_Draft]:
    names = CUMULATIVE_NAMES if schedule.naming == "cumulative" else QUARTER_NAMES
    for quarter in schedule.quarters:
        due = day_of_month(*add_months(year, quarter * 3, schedule.month_offset), schedule.day)
        name = names[quarter - 1]
        period = f"{year} год" if name == "год" else f"{name} {year}"
        yield _Draft(f"{year}-Q{quarter}", due, names=(("period_name", period),))


def _yearly(schedule: Yearly, year: int) -> Iterator[_Draft]:
    due = day_of_month(year + schedule.year_offset, schedule.month, schedule.day)
    yield _Draft(str(year), due, names=(("period_name", f"{year} год"),))


def _nds_thirds(schedule: NdsThirds, year: int) -> Iterator[_Draft]:
    for quarter in range(1, 5):
        names = (("period_name", f"{QUARTER_NAMES[quarter - 1]} {year}"),)
        for part in (1, 2, 3):
            due = day_of_month(*add_months(year, quarter * 3, part), schedule.day)
            yield _Draft(f"{year}-Q{quarter}", due, part=part, names=names)


def split_in_three(total: int) -> tuple[int, int, int]:
    """Деление на три платежа с округлением вниз, остаток — в третий."""
    third = total // 3
    return third, third, total - 2 * third


def add_calendar_months(day: date, months: int) -> date:
    return day_of_month(*add_months(day.year, day.month, months), day.day)


def _patent_payments(patents: Iterable[PatentLike], year: int) -> Iterator[_Draft]:
    """п. 2 ст. 346.51 НК РФ."""
    for patent in patents:
        if patent.date_start.year != year:
            continue
        # Если патент заканчивается 31 декабря, платить нужно не позднее 28 декабря.
        end = patent.date_end
        if (end.month, end.day) == (12, 31):
            end = date(end.year, 12, 28)
        last_day = patent.date_end + timedelta(days=1)
        six_months = add_calendar_months(patent.date_start, 6)
        number = f"№ {patent.number} " if patent.number else ""
        period = f"{number}{patent.date_start:%d.%m.%Y}–{patent.date_end:%d.%m.%Y}"
        names = (("period_name", period),)
        key = f"{year}-P{patent.id}"
        if last_day < six_months:
            yield _Draft(key, end, names=names, amount=patent.cost_kopecks)
            continue
        note = ""
        if last_day == six_months:
            note = (
                "Патент ровно на 6 месяцев: п. 2 ст. 346.51 НК РФ допускает два прочтения. "
                "Показан более ранний порядок (1/3 и 2/3) — проверьте."
            )
        first = None if patent.cost_kopecks is None else patent.cost_kopecks // 3
        rest = None if first is None else patent.cost_kopecks - first
        ninety = patent.date_start + timedelta(days=90)
        yield _Draft(key, min(ninety, end), 1, names, first, note)
        yield _Draft(key, end, 2, names, rest, note)


def _ndfl_december(year: int, work_calendar: WorkCalendar) -> Iterator[_Draft]:
    """п. 6 ст. 226 и п. 9 ст. 58 НК РФ: за 23–31 декабря — последний рабочий день года."""
    names = (("period_name", f"23–31 декабря {year}"),)
    yield _Draft(f"{year}-12", work_calendar.last_workday_of_year(year), names=names)


def _title(rule: Rule, draft: _Draft) -> str:
    values = dict(draft.names) | {"part": draft.part}
    try:
        return rule.title.format(**values)
    except (KeyError, IndexError, ValueError) as error:
        raise RulesError(f"{rule.code}: неизвестная подстановка в title: {error}") from None


def occurrences(
    book: RuleBook,
    company: object,
    patents: Iterable[PatentLike],
    work_calendar: WorkCalendar,
    date_from: date,
    date_to: date,
) -> list[Occurrence]:
    """Сроки компании, у которых дата (с переносом) не раньше date_from,
    а дата по закону не позже date_to."""
    patents = list(patents)
    result = []
    # Платёж может отстоять от года периода на два года (расписания с year_offset).
    for period_year in range(date_from.year - 2, date_to.year + 1):
        file = book.for_period_year(period_year)
        if file is None:
            continue
        for rule in file.rules:
            if not rule.applies.matches(company):
                continue
            schedule = rule.schedule
            match schedule:
                case Monthly():
                    drafts = _monthly(schedule, period_year)
                case Quarterly():
                    drafts = _quarterly(schedule, period_year)
                case Yearly():
                    drafts = _yearly(schedule, period_year)
                case NdsThirds():
                    drafts = _nds_thirds(schedule, period_year)
                case Handler(name="patent_payments"):
                    drafts = _patent_payments(patents, period_year)
                case Handler(name="ndfl_december"):
                    # календарь не нужен для лет вне диапазона
                    if not date_from.year <= period_year <= date_to.year:
                        continue
                    drafts = _ndfl_december(period_year, work_calendar)
            for draft in drafts:
                # сначала грубый отсев, чтобы не требовать календарь прошлых лет
                if draft.due > date_to or draft.due < date_from - timedelta(days=31):
                    continue
                # Прошлогодний срок без календаря того года уже прошёл: не запрашиваем его.
                if draft.due < date_from and draft.due.year not in work_calendar.years:
                    continue
                due = work_calendar.shift_to_workday(draft.due)
                if due < date_from:
                    continue
                result.append(
                    Occurrence(
                        rule_code=rule.code,
                        period_key=draft.period_key,
                        period_year=period_year,
                        part=draft.part,
                        kind=rule.kind,
                        title=_title(rule, draft),
                        description=" ".join(filter(None, (rule.description, draft.note))),
                        source_ref=rule.source,
                        original_due_date=draft.due,
                        due_date=due,
                        needs_amount=rule.needs_amount,
                        client_visible=rule.client_visible,
                        amount_kopecks=draft.amount,
                    )
                )
    return sorted(result, key=lambda item: (item.due_date, item.rule_code, item.part))
