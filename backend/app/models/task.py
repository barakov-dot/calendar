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
        Index("ix_tasks_company_due", "company_id", "due_date"),
        Index("ix_tasks_status_due", "status", "due_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    source: Mapped[str] = mapped_column(String(16))
    rule_code: Mapped[str | None] = mapped_column(String(64))
    period_key: Mapped[str | None] = mapped_column(String(32))
    part: Mapped[int] = mapped_column(default=1, server_default="1")
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    source_ref: Mapped[str] = mapped_column(String(500), default="", server_default="")
    due_date: Mapped[date]
    original_due_date: Mapped[date]
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


class WorkDay(Base):
    """Производственный календарь: все дни загруженных лет."""

    __tablename__ = "work_calendar"

    date: Mapped[dt.date] = mapped_column(primary_key=True)
    is_workday: Mapped[bool]
    note: Mapped[str] = mapped_column(String(255), default="", server_default="")
