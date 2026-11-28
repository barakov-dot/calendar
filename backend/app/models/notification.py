from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.user import Timestamp, one_of


class NotificationType(StrEnum):
    DIGEST = "digest"
    REMINDER = "reminder"
    OVERDUE = "overdue"
    CLIENT_MARKED_PAID = "client_marked_paid"
    FILL_AMOUNT = "fill_amount"
    ATTACHMENT = "attachment"  # клиент приложил файл
    SIGNATURE = "signature"  # заканчивается срок электронной подписи
    BROADCAST = "broadcast"  # рассылка администратора
    DEMAND = "demand"  # приближается срок по требованию инспекции
    DEMAND_SHARE = "demand_share"  # требование отправили получателю


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"  # к моменту отправки стало неактуально


class NotificationSettings(Base):
    """Личные настройки поверх значений из settings.json (пусто — по умолчанию)."""

    __tablename__ = "notification_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    offsets_days: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))
    on_due_day: Mapped[bool | None]
    daily_digest: Mapped[bool] = mapped_column(default=True, server_default="true")
    # во сколько по своему времени получать напоминания о сроках
    digest_time: Mapped[str | None] = mapped_column(String(5))
    timezone: Mapped[str | None] = mapped_column(String(40))


class Broadcast(Base):
    """Сообщение администратора группе пользователей."""

    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text)
    # выбранные группы; пусто — получателей отмечали по одному
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(16)))
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())


class Notification(Base):
    """Журнал и очередь отправки."""

    __tablename__ = "notifications_log"
    __table_args__ = (
        # защита от дублей; пустой task_id (дайджест) тоже участвует в сравнении
        UniqueConstraint(
            "user_id",
            "task_id",
            "type",
            "scheduled_for",
            "broadcast_id",
            name="uq_notifications_log_key",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(one_of("type", NotificationType), name="type"),
        CheckConstraint(one_of("status", NotificationStatus), name="status"),
        Index("ix_notifications_log_queue", "status", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    broadcast_id: Mapped[int | None] = mapped_column(
        ForeignKey("broadcasts.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(32))
    scheduled_for: Mapped[date]
    # пояснение отправителя к сообщению
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(Timestamp)
    sent_at: Mapped[datetime | None] = mapped_column(Timestamp)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
