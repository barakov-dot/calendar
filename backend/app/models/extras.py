"""Замещения бухгалтеров, электронные подписи и файлы к задачам."""

from datetime import date, datetime

from sqlalchemy import CheckConstraint, ForeignKey, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.user import Timestamp


class Substitution(Base):
    """Кто заменяет бухгалтера в указанные дни (обе даты включительно)."""

    __tablename__ = "substitutions"
    __table_args__ = (
        CheckConstraint("date_to >= date_from", name="dates"),
        CheckConstraint("substitute_id <> accountant_id", name="other_person"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    accountant_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    substitute_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    date_from: Mapped[date]
    date_to: Mapped[date]
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())


class Signature(Base):
    """Электронная подпись компании: следим за сроком действия."""

    __tablename__ = "signatures"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    holder: Mapped[str] = mapped_column(String(200))
    expires_on: Mapped[date]
    notify_client: Mapped[bool] = mapped_column(default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())


class Attachment(Base):
    """Файл к задаче (платёжка). Хранится в базе и попадает в резервные копии."""

    __tablename__ = "task_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(64))
    size: Mapped[int]
    # содержимое не читается вместе со списком
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
