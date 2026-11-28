"""Виды требований из rules/demands.yaml."""

from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_config
from app.services.calendar.workdays import WorkCalendar


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Kind(Strict):
    knd: str = ""
    name: str = Field(min_length=1)
    short: str = Field(min_length=1)
    action: str = Field(min_length=1)
    task_kind: Literal["payment", "other"]
    response_workdays: int | None = Field(None, ge=1, le=60)
    response_label: str = "Срок исполнения"
    # срок исполнения — день загрузки документа, а не расчёт от квитанции
    due_on_upload: bool = False
    source: str = Field(min_length=1)


class Receipt(Strict):
    workdays: int = Field(ge=1, le=30)
    source: str = Field(min_length=1)


class Book(Strict):
    receipt: Receipt
    types: list[Kind]
    other: Kind

    def kind(self, knd: str) -> Kind:
        return next((item for item in self.types if item.knd == knd), self.other)


@lru_cache(maxsize=4)
def _read(path: str, modified: int) -> Book:
    return Book.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def get_book() -> Book:
    """Файл перечитывается, когда изменился."""
    path = Path(get_config().rules_path) / "demands.yaml"
    return _read(str(path), path.stat().st_mtime_ns)


def add_workdays(calendar: WorkCalendar, start: date, count: int) -> date:
    """count-й рабочий день после start: срок начинается на следующий день (ст. 6.1 НК РФ)."""
    day = start
    while count > 0:
        day += timedelta(days=1)
        count -= calendar.is_workday(day)
    return day
