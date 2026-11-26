"""Одноразовые приглашения бухгалтеров и клиентов."""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Invite, InviteKind, Role, User
from app.services import audit
from app.services.users import get_by_telegram_id

INVITE_TTL = timedelta(days=7)
DEEPLINK_PREFIX = "inv_"


class InviteError(Exception):
    """Приглашение нельзя принять. Текст показывается пользователю."""


INVALID = "Приглашение недействительно или уже использовано. Попросите новое."


@dataclass(frozen=True)
class TelegramProfile:
    telegram_id: int
    first_name: str = ""
    last_name: str = ""
    username: str = ""


async def create(
    db: AsyncSession,
    kind: InviteKind,
    created_by: User,
    company_id: int | None = None,
    can_mark_paid: bool = False,
) -> Invite:
    invite = Invite(
        token=secrets.token_urlsafe(32),
        kind=kind,
        company_id=company_id,
        can_mark_paid=can_mark_paid,
        created_by=created_by.id,
        expires_at=datetime.now(UTC) + INVITE_TTL,
    )
    db.add(invite)
    await db.flush()
    audit.record(db, created_by.id, "invite.create", "invite", invite.id, {"kind": kind})
    await db.commit()
    await db.refresh(invite)
    return invite


def _is_open(invite: Invite | None) -> bool:
    return (
        invite is not None
        and invite.used_at is None
        and invite.revoked_at is None
        and invite.expires_at > datetime.now(UTC)
    )


def _check_role(user: User | None, invite: Invite) -> None:
    if user is None:
        return
    if not user.is_active:
        raise InviteError("Ваш доступ отключён. Обратитесь к администратору.")
    # Клиент может получить несколько приглашений: по одному на компанию.
    if user.role != invite.kind:
        raise InviteError(
            "Вы уже зарегистрированы с другой ролью, приглашение не использовано. "
            "Обратитесь к администратору."
        )
    if user.role == Role.ACCOUNTANT and user.pd_consent_at is not None:
        raise InviteError("Вы уже подключены как бухгалтер.")


async def check(db: AsyncSession, token: str, telegram_id: int) -> None:
    """Проверяет без изменений в базе, можно ли принять приглашение."""
    invite = await db.scalar(select(Invite).where(Invite.token == token))
    if not _is_open(invite):
        raise InviteError(INVALID)
    _check_role(await get_by_telegram_id(db, telegram_id), invite)


async def accept(db: AsyncSession, token: str, profile: TelegramProfile) -> User:
    """Принимает приглашение вместе с согласием на обработку ПДн."""
    # FOR UPDATE: два одновременных нажатия не используют приглашение дважды.
    invite = await db.scalar(select(Invite).where(Invite.token == token).with_for_update())
    try:
        if not _is_open(invite):
            raise InviteError(INVALID)
        user = await get_by_telegram_id(db, profile.telegram_id)
        _check_role(user, invite)
    except InviteError:
        await db.rollback()
        raise
    now = datetime.now(UTC)
    if user is None:
        user = User(telegram_id=profile.telegram_id, role=invite.kind)
        db.add(user)
    user.first_name = profile.first_name
    user.last_name = profile.last_name
    user.username = profile.username
    user.pd_consent_at = user.pd_consent_at or now
    await db.flush()
    invite.used_by = user.id
    invite.used_at = now
    audit.record(db, user.id, "invite.accept", "invite", invite.id, {"kind": invite.kind})
    await db.commit()
    return user


async def list_open(db: AsyncSession) -> list[Invite]:
    result = await db.scalars(
        select(Invite)
        .where(
            Invite.used_at.is_(None),
            Invite.revoked_at.is_(None),
            Invite.expires_at > datetime.now(UTC),
        )
        .order_by(Invite.id.desc())
    )
    return list(result)


async def revoke(db: AsyncSession, invite_id: int, user: User) -> bool:
    invite = await db.get(Invite, invite_id, with_for_update=True)
    if not _is_open(invite):
        await db.rollback()
        return False
    invite.revoked_at = datetime.now(UTC)
    audit.record(db, user.id, "invite.revoke", "invite", invite.id)
    await db.commit()
    return True
