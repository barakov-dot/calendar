"""Рассылка сообщений пользователям. Отправляет воркер через общую очередь."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import business_today
from app.models import (
    EDITORS,
    Broadcast,
    Company,
    CompanyMember,
    CompanyStaff,
    Notification,
    NotificationType,
    Role,
    User,
)
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


# кого из привязанных к организации можно выбрать
COMPANY_GROUPS = {"client": (Role.CLIENT,), "accountant": EDITORS, "assistant": (Role.ASSISTANT,)}


def _linked(company_ids: list[int], group: str):
    """Люди выбранной группы, привязанные хотя бы к одной из организаций."""
    link = CompanyMember if group == "client" else CompanyStaff
    members = select(link.user_id).where(link.company_id.in_(company_ids))
    return User.id.in_(members) & User.role.in_(COMPANY_GROUPS[group])


async def recipients(
    db: AsyncSession,
    actor: User,
    roles: list[str],
    user_ids: list[int],
    company_ids: list[int] | None = None,
    company_groups: list[str] | None = None,
) -> Recipients:
    """Выбранные роли, люди выбранных организаций и отдельно отмеченные, без повторов.

    Себе отправитель пишет, только если выбрал себя поимённо.
    """
    conditions = []
    if roles:
        # отключённые не входят в группы вовсе
        conditions.append(User.role.in_(roles) & User.is_active.is_(True) & (User.id != actor.id))
    for group in company_groups or []:
        if company_ids:
            linked = _linked(company_ids, group)
            conditions.append(linked & User.is_active.is_(True) & (User.id != actor.id))
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
    db: AsyncSession,
    actor: User,
    text: str,
    roles: list[str],
    user_ids: list[int],
    company_ids: list[int] | None = None,
    company_groups: list[str] | None = None,
) -> Broadcast:
    found = await recipients(db, actor, roles, user_ids, company_ids, company_groups)
    if not found.ready:
        raise BroadcastError("Некому отправить: никто из выбранных не получает сообщения бота")
    item = Broadcast(
        created_by=actor.id,
        text=text,
        roles=sorted({Role(role) for role in roles}),
        company_ids=sorted(set(company_ids or [])) if company_groups else [],
        company_groups=sorted(set(company_groups or [])) if company_ids else [],
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


async def history(
    db: AsyncSession, archived: bool = False, limit: int = 50
) -> list[tuple[Broadcast, str, dict[str, int]]]:
    """Последние рассылки: действующий список или архив."""
    shown = Broadcast.archived_at.is_not(None) if archived else Broadcast.archived_at.is_(None)
    query = select(Broadcast).where(shown).order_by(Broadcast.id.desc()).limit(limit)
    items = list(await db.scalars(query))
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


async def company_names(db: AsyncSession, ids: set[int]) -> dict[int, str]:
    rows = await db.scalars(select(Company).where(Company.id.in_(ids)))
    return {company.id: company.short_name or company.name for company in rows}


async def archive(db: AsyncSession, actor: User, ids: list[int], archived: bool) -> None:
    """Убирает рассылки из списка или возвращает. Отправка из очереди продолжается."""
    items = await db.scalars(select(Broadcast).where(Broadcast.id.in_(ids)))
    for item in items:
        if (item.archived_at is not None) != archived:
            item.archived_at = datetime.now(UTC) if archived else None
            action = "broadcast.archive" if archived else "broadcast.restore"
            audit.record(db, actor.id, action, "broadcast", item.id)
    await db.commit()


async def delete(db: AsyncSession, actor: User, item: Broadcast) -> None:
    """Удаляет из истории; неотправленное убирается из очереди. Доставленное остаётся
    у получателей в Telegram."""
    audit.record(db, actor.id, "broadcast.delete", "broadcast", item.id)
    await db.delete(item)
    await db.commit()
