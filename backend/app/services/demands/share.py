"""Отправка требования людям через бота: клиентам, бухгалтерам и помощникам организации."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import business_today
from app.models import (
    Company,
    CompanyMember,
    Demand,
    DemandStep,
    Notification,
    NotificationType,
    Role,
    Task,
    User,
)
from app.services import audit, staff, substitutions
from app.services.broadcasts import why_unreachable
from app.services.demands.service import DemandError
from app.services.notify.queue import enqueue

# вместе с реквизитами укладывается в подпись к файлу Telegram (1024 знака)
COMMENT_LIMIT = 700


@dataclass
class Recipient:
    user: User
    group: str
    reason: str | None
    status: str | None = None
    sent_at: datetime | None = None


async def _anchor_task(db: AsyncSession, demand: Demand) -> int:
    """Задача, к которой привязываются отправки: срок ответа, а если его нет — квитанция."""
    rows = await db.execute(select(Task.demand_step, Task.id).where(Task.demand_id == demand.id))
    found = dict(rows.all())
    return found.get(DemandStep.RESPONSE) or found[DemandStep.RECEIPT]


async def candidates(db: AsyncSession, demand: Demand) -> list[Recipient]:
    """Действующие получатели: клиенты, бухгалтеры и замещающие, помощники организации."""
    company = await db.get(Company, demand.company_id)
    found: dict[int, Recipient] = {}

    async def add(group: str, condition) -> None:
        users = await db.scalars(
            select(User).where(condition, User.is_active.is_(True)).order_by(User.id)
        )
        for user in users:
            found.setdefault(user.id, Recipient(user, group, why_unreachable(user)))

    members = select(CompanyMember.user_id).where(CompanyMember.company_id == company.id)
    await add("client", User.id.in_(members) & (User.role == Role.CLIENT))
    team = await staff.team(db, company.id)
    if team.accountants:
        replaced = await substitutions.active(db, business_today())
        ids = {
            user_id
            for accountant in team.accountants
            for user_id in (accountant.id, *replaced.get(accountant.id, []))
        }
        await add("accountant", User.id.in_(ids) & User.role.in_(substitutions.STAFF))
    await add("assistant", User.id.in_([user.id for user in team.assistants]))
    return list(found.values())


async def recipients(db: AsyncSession, demand: Demand) -> list[Recipient]:
    """Получатели вместе с тем, что им уже отправляли."""
    found = await candidates(db, demand)
    rows = await db.scalars(
        select(Notification)
        .where(
            Notification.task_id == await _anchor_task(db, demand),
            Notification.type == NotificationType.DEMAND_SHARE,
        )
        .order_by(Notification.scheduled_for, Notification.id)
        .execution_options(populate_existing=True)
    )
    latest = {row.user_id: row for row in rows}
    for item in found:
        if row := latest.get(item.user.id):
            item.status, item.sent_at = row.status, row.sent_at
    return found


async def send(
    db: AsyncSession, actor: User, demand: Demand, user_ids: set[int], comment: str
) -> None:
    allowed = {item.user.id: item for item in await candidates(db, demand)}
    if not user_ids <= allowed.keys():
        raise DemandError("Среди получателей есть не связанные с организацией")
    ready = [user_id for user_id in sorted(user_ids) if allowed[user_id].reason is None]
    if not ready:
        raise DemandError("Некому отправить: выбранные не получают сообщения бота")
    task_id = await _anchor_task(db, demand)
    for user_id in ready:
        await enqueue(
            db,
            user_id,
            NotificationType.DEMAND_SHARE,
            business_today(),
            task_id,
            again=True,
            note=comment,
        )
    # комментарий может содержать персональные данные, в журнал не пишется
    audit.record(db, actor.id, "demand.share", "demand", demand.id, {"user_ids": ready})
    await db.commit()
