import datetime as dt
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.user import Timestamp, one_of


class TaskSource(StrEnum):
    RULE = "rule"
    CUSTOM = "custom"


class TaskKind(StrEnum):
    PAYMENT = "payment"
    REPORT = "report"
    NOTICE = "notice"
    OTHER = "other"


class TaskStatus(StrEnum):
    PLANNED = "planned"
    DONE = "done"  # отчёт сдан
    PAID = "paid"
    NOT_REQUIRED = "not_required"


class ChangedBy(StrEnum):
    ACCOUNTANT = "accountant"
    ADMIN = "admin"
    CHIEF = "chief"
    CLIENT = "client"
    SYSTEM = "system"  # статус выставила генерация: правило перестало подходить


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        # Ключ идемпотентной генерации. У своих задач rule_code пуст и ключ не действует.
        UniqueConstraint(
            "company_id", "rule_code", "period_key", "part", name="uq_tasks_generation_key"
        ),
        CheckConstraint(one_of("source", TaskSource), name="source"),
        CheckConstraint(one_of("kind", TaskKind), name="kind"),
        CheckConstraint(one_of("status", TaskStatus), name="status"),
        CheckConstraint(one_of("status_changed_by_role", ChangedBy), name="changed_by_role"),
        CheckConstraint("part BETWEEN 1 AND 3", name="part"),
        CheckConstraint("amount_kopecks >= 0", name="amount"),
        # у задачи есть компания или, у личного напоминания, владелец
        CheckConstraint("(company_id IS NULL) <> (owner_id IS NULL)", name="company_or_owner"),
        # повторное разворачивание напоминания не создаёт дублей
        Index(
            "uq_tasks_reminder_occurrence",
            "recurring_reminder_id",
            "period_key",
            "company_id",
            "owner_id",
            unique=True,
            postgresql_where=text("recurring_reminder_id IS NOT NULL"),
            postgresql_nulls_not_distinct=True,
        ),
        # у требования по одной задаче на каждый шаг
        UniqueConstraint("demand_id", "demand_step", name="uq_tasks_demand_step"),
        Index("ix_tasks_company_due", "company_id", "due_date"),
        Index("ix_tasks_status_due", "status", "due_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    recurring_reminder_id: Mapped[int | None] = mapped_column(
        ForeignKey("recurring_reminders.id", ondelete="SET NULL")
    )
    # напоминание о сроке электронной подписи; меняется только через неё
    signature_id: Mapped[int | None] = mapped_column(
        ForeignKey("signatures.id", ondelete="CASCADE"), unique=True
    )
    # шаг требования инспекции; меняется только через требование
    demand_id: Mapped[int | None] = mapped_column(ForeignKey("demands.id", ondelete="CASCADE"))
    demand_step: Mapped[str | None] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16))
    rule_code: Mapped[str | None] = mapped_column(String(64))
    period_key: Mapped[str | None] = mapped_column(String(32))
    part: Mapped[int] = mapped_column(default=1, server_default="1")
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    # из правила: «что сделать» и «за какой период»; у своих задач пусто
    action_title: Mapped[str] = mapped_column(String(200), default="", server_default="")
    period_label: Mapped[str] = mapped_column(String(200), default="", server_default="")
    source_ref: Mapped[str] = mapped_column(String(500), default="", server_default="")
    due_date: Mapped[date]
    original_due_date: Mapped[date]
    # срок изменён вручную: генерация его не трогает
    due_overridden: Mapped[bool] = mapped_column(default=False, server_default="false")
    amount_kopecks: Mapped[int | None] = mapped_column(BigInteger)
    amount_overridden: Mapped[bool] = mapped_column(default=False, server_default="false")
    needs_amount: Mapped[bool] = mapped_column(default=False, server_default="false")
    status: Mapped[str] = mapped_column(String(16), default="planned", server_default="planned")
    client_visible: Mapped[bool] = mapped_column(default=False, server_default="false")
    status_changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status_changed_at: Mapped[datetime | None] = mapped_column(Timestamp)
    status_changed_by_role: Mapped[str | None] = mapped_column(String(16))
    comment: Mapped[str] = mapped_column(Text, default="", server_default="")  # клиент не видит
    client_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())


class ShiftRule(StrEnum):
    NONE = "none"
    NEXT_WORKDAY = "next_workday"
    PREV_WORKDAY = "prev_workday"


class Audience(StrEnum):
    ACCOUNTANT = "accountant"
    CLIENT = "client"
    BOTH = "both"


class RecurringReminder(Base):
    """Свои повторяющиеся задачи. company_id пуст — личное напоминание сотрудника."""

    __tablename__ = "recurring_reminders"
    __table_args__ = (
        CheckConstraint(one_of("kind", TaskKind), name="kind"),
        CheckConstraint(one_of("shift_rule", ShiftRule), name="shift_rule"),
        CheckConstraint(one_of("audience", Audience), name="audience"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    kind: Mapped[str] = mapped_column(String(16))
    rrule: Mapped[str] = mapped_column(String(200))
    dtstart: Mapped[date]
    until: Mapped[date | None]
    shift_rule: Mapped[str] = mapped_column(String(16))
    audience: Mapped[str] = mapped_column(String(16))
    client_visible: Mapped[bool] = mapped_column(default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())


class WorkDay(Base):
    """Производственный календарь: все дни загруженных лет."""

    __tablename__ = "work_calendar"

    date: Mapped[dt.date] = mapped_column(primary_key=True)
    is_workday: Mapped[bool]
    note: Mapped[str] = mapped_column(String(255), default="", server_default="")
