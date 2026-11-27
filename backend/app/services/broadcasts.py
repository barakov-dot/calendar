"""Рассылка сообщений пользователям. Отправляет воркер через общую очередь."""

from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import business_today
from app.models import Broadcast, Notification, NotificationType, Role, User
from app.services import audit
from app.services.companies import person_name


class BroadcastError(Exception):
    """Рассылку нельзя отправить. Текст показывается пользователю."""


@dataclass
class Recipients:
    ready: list[User]
    # (пользователь, почему ему не придёт)
    unreachable: list[tuple[User, str]]


def why_unreachable(user: User) -> str | None:
    if not user.is_active:
        return "доступ отключён"
    if user.pd_consent_at is None:
        return "ещё не подключился к боту"
    if user.bot_blocked:
        return "заблокировал(а) бота"
    if user.telegram_id <= 0:
        return "тестовый пользователь"
    return None


async def recipients(
    db: AsyncSession, actor: User, roles: list[str], user_ids: list[int]
) -> Recipients:
    """Выбранные роли и отдельно выбранные пользователи, без повторов.

    Себе отправитель пишет, только если выбрал себя поимённо.
    """
    conditions = []
    if roles:
        # отключённые не входят в группы вовсе
        conditions.append(User.role.in_(roles) & User.is_active.is_(True) & (User.id != actor.id))
    if user_ids:
        conditions.append(User.id.in_(user_ids))
    found = Recipients([], [])
    if not conditions:
        return found
    for user in await db.scalars(select(User).where(or_(*conditions)).order_by(User.id)):
        if reason := why_unreachable(user):
            found.unreachable.append((user, reason))
        else:
            found.ready.append(user)
    return found


async def create(
    db: AsyncSession, actor: User, text: str, roles: list[str], user_ids: list[int]
) -> Broadcast:
    found = await recipients(db, actor, roles, user_ids)
    if not found.ready:
        raise BroadcastError("Некому отправить: никто из выбранных не получает сообщения бота")
    item = Broadcast(
        created_by=actor.id,
        text=text,
        roles=sorted({Role(role) for role in roles}),
    )
    db.add(item)
    await db.flush()
    today = business_today()
    db.add_all(
        Notification(
            user_id=user.id,
            type=NotificationType.BROADCAST,
            scheduled_for=today,
            broadcast_id=item.id,
        )
        for user in found.ready
    )
    audit.record(
        db, actor.id, "broadcast.create", "broadcast", item.id, {"recipients": len(found.ready)}
    )
    await db.commit()
    return item


async def history(db: AsyncSession, limit: int = 50) -> list[tuple[Broadcast, str, dict[str, int]]]:
    items = list(await db.scalars(select(Broadcast).order_by(Broadcast.id.desc()).limit(limit)))
    counts: dict[int, dict[str, int]] = {item.id: {} for item in items}
    rows = await db.execute(
        select(Notification.broadcast_id, Notification.status, func.count())
        .where(Notification.broadcast_id.in_(counts))
        .group_by(Notification.broadcast_id, Notification.status)
    )
    for broadcast_id, status, total in rows:
        counts[broadcast_id][status] = total
    result = []
    for item in items:
        author = await db.get(User, item.created_by)
        result.append((item, person_name(author), counts[item.id]))
    return result


async def deliveries(db: AsyncSession, broadcast_id: int) -> list[tuple[User, str]]:
    rows = await db.execute(
        select(User, Notification.status)
        .join(Notification, Notification.user_id == User.id)
        .where(Notification.broadcast_id == broadcast_id)
        .order_by(func.lower(User.first_name), User.id)
    )
    return [(user, status) for user, status in rows]
