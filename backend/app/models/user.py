from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Role(StrEnum):
    ADMIN = "admin"
    CHIEF = "chief"  # главный бухгалтер: все компании и люди, без настроек сервиса
    ACCOUNTANT = "accountant"
    ASSISTANT = "assistant"  # помощник бухгалтера: видит всё, ничего не меняет
    CLIENT = "client"


# руководят работой: все компании, пользователи, приглашения, замещения
MANAGERS = (Role.ADMIN, Role.CHIEF)
# вправе менять компании и задачи (бухгалтер — только свои)
EDITORS = (Role.ADMIN, Role.CHIEF, Role.ACCOUNTANT)


class InviteKind(StrEnum):
    CHIEF = "chief"
    ACCOUNTANT = "accountant"
    ASSISTANT = "assistant"
    CLIENT = "client"


def one_of(column: str, values: type[StrEnum]) -> str:
    return f"{column} IN ({', '.join(repr(str(value)) for value in values)})"


Timestamp = DateTime(timezone=True)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(one_of("role", Role), name="role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    first_name: Mapped[str] = mapped_column(String(255), default="", server_default="")
    last_name: Mapped[str] = mapped_column(String(255), default="", server_default="")
    username: Mapped[str] = mapped_column(String(255), default="", server_default="")
    # имя задал администратор: данные из Telegram его не перезаписывают
    name_overridden: Mapped[bool] = mapped_column(default=False, server_default="false")
    role: Mapped[str] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
    bot_blocked: Mapped[bool] = mapped_column(default=False, server_default="false")
    pd_consent_at: Mapped[datetime | None] = mapped_column(Timestamp)
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())


class Invite(Base):
    __tablename__ = "invites"
    __table_args__ = (CheckConstraint(one_of("kind", InviteKind), name="kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(16))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), index=True)
    can_mark_paid: Mapped[bool] = mapped_column(default=False, server_default="false")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(Timestamp)
    used_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    used_at: Mapped[datetime | None] = mapped_column(Timestamp)
    revoked_at: Mapped[datetime | None] = mapped_column(Timestamp)


class LoginRequest(Base):
    __tablename__ = "login_requests"

    nonce: Mapped[str] = mapped_column(String(64), primary_key=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger)
    confirmed_at: Mapped[datetime | None] = mapped_column(Timestamp)
    expires_at: Mapped[datetime] = mapped_column(Timestamp, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(Timestamp)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now(), index=True)
