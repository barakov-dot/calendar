"""Запись о форме из ответа Росстата."""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Form:
    key: str
    index: str
    name: str
    okud: str
    periodicity: str
    period: str
    deadline: str
    due_date: date | None
    comment: str


def _text(item: dict[str, Any], name: str, limit: int) -> str:
    value = item.get(name)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def parse_date(value: Any) -> date | None:
    """Срок сдачи: ISO, «дд.мм.гггг» или отметка времени в миллисекундах."""
    if isinstance(value, int) and value > 10**11:
        try:
            return (
                datetime.fromtimestamp(value / 1000, UTC)
                .astimezone(ZoneInfo("Europe/Moscow"))
                .date()
            )
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    if match := re.search(r"(?<!\d)(20\d\d)-(\d\d)-(\d\d)", value):
        year, month, day = match.groups()
    elif match := re.search(r"(?<!\d)(\d\d)\.(\d\d)\.(20\d\d)(?!\d)", value):
        day, month, year = match.groups()
    else:
        return None
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def parse_form(item: dict[str, Any]) -> Form | None:
    name = _text(item, "name", 1000)
    index = _text(item, "index", 64)
    if not name and not index:
        return None
    period = _text(item, "reported_period", 200) or _text(item, "formatted_period", 200)
    due = parse_date(item.get("end_time"))
    deadline = f"{due:%d.%m.%Y}" if due else _text(item, "end_time", 200)
    identity = _text(item, "id", 64) or _text(item, "okud", 32) or index
    return Form(
        # одна форма за один отчётный период — одна запись, даже если срок перенесли
        key=f"{identity}|{period or deadline}"[:300],
        index=index,
        name=name,
        okud=_text(item, "okud", 32),
        periodicity=_text(item, "form_period", 100) or _text(item, "periodicity", 100),
        period=period,
        deadline=deadline,
        due_date=due,
        comment=_text(item, "comment", 2000),
    )
