from datetime import date
from pathlib import Path
from types import SimpleNamespace

from app.schemas.company import CompanyData
from app.services.calendar.workdays import WorkCalendar, read_calendar_file
from app.services.inn import with_check_digits
from app.services.rules.engine import load_rules, occurrences

CALENDAR_DIR = Path("/app/data/calendar")
RULES_DIR = Path("/app/rules")

book = load_rules(RULES_DIR)


def work_calendar() -> WorkCalendar:
    days = {}
    for year in (2026, 2027):
        days |= read_calendar_file(CALENDAR_DIR / f"{year}.json").days()
    return WorkCalendar(days)


def company(entity: str = "ooo", regime: str = "usn6", **fields) -> CompanyData:
    base = "000000001" if entity == "ooo" else "0000000001"
    return CompanyData(
        inn=with_check_digits(base), name="Тест", entity_type=entity, main_regime=regime, **fields
    )


def patent(start: date, end: date, cost: int | None = 100_000_00, number: int = 1):
    return SimpleNamespace(
        id=number, number=str(number), date_start=start, date_end=end, cost_kopecks=cost
    )


def schedule(
    target: CompanyData,
    patents=(),
    date_from: date = date(2026, 1, 1),
    date_to: date = date(2026, 12, 31),
):
    return occurrences(book, target, patents, work_calendar(), date_from, date_to)


def dues(items, code: str, period: str | None = None) -> list[date]:
    return [
        item.due_date
        for item in items
        if item.rule_code == code and (period is None or item.period_key == period)
    ]
