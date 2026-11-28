"""Схемы задач и напоминаний. Клиенту отдаётся только ClientTaskOut."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import Audience, ShiftRule, TaskKind, TaskStatus
from app.schemas.company import MAX_KOPECKS, Input
from app.services.reminders import Schedule

Title = Field(min_length=1, max_length=300)
Text = Field("", max_length=10000)
Amount = Field(None, ge=0, le=MAX_KOPECKS)


class ClientTaskOut(BaseModel):
    """Без внутреннего комментария, признаков и истории."""

    id: int
    company_id: int | None
    company_name: str
    kind: str
    title: str
    due_date: date
    amount_kopecks: int | None
    status: str
    client_note: str
    source_ref: str
    has_files: bool = False
    # срок раньше начала ведения календаря: не просрочка
    before_start: bool = False
    # доступные клиенту действия; у сотрудников всегда false
    can_mark_paid: bool = False
    can_unmark_paid: bool = False


class TaskOut(ClientTaskOut):
    source: str
    rule_code: str | None
    period_key: str | None
    part: int
    description: str
    original_due_date: date
    due_overridden: bool
    amount_overridden: bool
    needs_amount: bool
    client_visible: bool
    action_title: str
    period_label: str
    comment: str
    status_changed_at: datetime | None
    status_changed_by_name: str
    status_changed_by_role: str | None
    recurring_reminder_id: int | None
    signature_id: int | None
    demand_id: int | None
    rosstat_form_id: int | None


class NdsPart(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    part: int
    due_date: date
    amount_kopecks: int | None
    amount_overridden: bool
    status: str


class TaskDetail(TaskOut):
    # все три части квартального НДС; пусто для остальных задач
    nds_parts: list[NdsPart] = Field(default_factory=list)


class TaskList(BaseModel):
    items: list[TaskOut] | list[ClientTaskOut]
    total: int
    today: date


class TaskCreate(Input):
    # без компании — личная задача сотрудника
    company_id: int | None = None
    title: str = Title
    description: str = Text
    kind: TaskKind = TaskKind.OTHER
    due_date: date
    amount_kopecks: int | None = Amount
    comment: str = Text
    client_note: str = Text
    client_visible: bool = False


class TaskPatch(Input):
    """Меняются только переданные поля. Сумму можно очистить значением null."""

    title: str | None = Field(None, min_length=1, max_length=300)
    description: str | None = Field(None, max_length=10000)
    due_date: date | None = None
    # вернуть срок по правилам
    reset_due: bool = False
    amount_kopecks: int | None = Amount
    status: TaskStatus | None = None
    comment: str | None = Field(None, max_length=10000)
    client_note: str | None = Field(None, max_length=10000)
    client_visible: bool | None = None


class BulkIn(Input):
    ids: list[int] = Field(min_length=1, max_length=1000)
    status: TaskStatus


class BulkOut(BaseModel):
    updated: int
    # статус неприменим к типу задачи или уже установлен
    skipped: int


class ReminderIn(Input):
    company_id: int | None = None
    title: str = Title
    description: str = Text
    kind: TaskKind = TaskKind.OTHER
    amount_kopecks: int | None = Amount
    schedule: Schedule
    dtstart: date
    until: date | None = None
    shift_rule: ShiftRule = ShiftRule.NEXT_WORKDAY
    audience: Audience = Audience.ACCOUNTANT
    is_active: bool = True


class ReminderOut(ReminderIn):
    model_config = ConfigDict(extra="ignore")

    id: int
    company_name: str
    created_by_name: str
    next_dates: list[date]
    editable: bool
