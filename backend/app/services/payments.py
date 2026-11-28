"""Отметка оплаты клиентом («Клиент платит сам») и её отмена."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import editable_task_condition, visible_task_condition
from app.core.settings_store import get_settings
from app.models import (
    EDITORS,
    CompanyMember,
    NotificationType,
    Role,
    Task,
    TaskKind,
    TaskStatus,
    User,
)
from app.services import audit, staff, substitutions, tasks
from app.services.notify.queue import enqueue


class PaymentError(Exception):
    """Текст показывается пользователю. code — HTTP-статус."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


def not_found() -> PaymentError:
    return PaymentError("Задача не найдена", 404)


NOT_ALLOWED = "Отмечать оплату может клиент, которому это разрешил бухгалтер"


async def payer_company_ids(db: AsyncSession, user: User) -> set[int]:
    """Компании, по которым этот клиент вправе отмечать оплату."""
    return set(
        await db.scalars(
            select(CompanyMember.company_id).where(
                CompanyMember.user_id == user.id, CompanyMember.can_mark_paid.is_(True)
            )
        )
    )


def can_unmark(task: Task, user: User, now: datetime) -> bool:
    """Клиент отменяет только свою отметку и только в отведённое время."""
    hours = get_settings().tasks.client_can_unmark_own_paid_hours
    return (
        task.status == TaskStatus.PAID
        and task.status_changed_by == user.id
        and task.status_changed_by_role == Role.CLIENT
        and task.status_changed_at is not None
        and now - task.status_changed_at <= timedelta(hours=hours)
    )


async def _client_task(db: AsyncSession, user: User, task_id: int) -> Task:
    show_notices = get_settings().tasks.show_notices_to_clients
    task = await db.scalar(
        select(Task)
        .where(Task.id == task_id, visible_task_condition(user, show_notices))
        .with_for_update()
    )
    if task is None:
        raise not_found()
    if task.company_id not in await payer_company_ids(db, user):
        raise PaymentError(NOT_ALLOWED, 403)
    if task.kind != TaskKind.PAYMENT:
        raise PaymentError("Отметить оплату можно только у платежа", 403)
    return task


def _change(task: Task, status: str, user: User) -> None:
    task.status = status
    task.status_changed_by = user.id
    task.status_changed_by_role = user.role
    task.status_changed_at = datetime.now(UTC)


async def responsible(db: AsyncSession, company_id: int) -> list[User]:
    """Кому писать по компании: её бухгалтеры (или замещающие), а если никого —
    администраторы."""
    team = await staff.team(db, company_id)
    if team.accountants:
        replaced = await substitutions.active(db, tasks.today())
        ids = dict.fromkeys(
            user_id
            for accountant in team.accountants
            for user_id in substitutions.recipients(replaced, accountant.id)
        )
        found = [await db.get(User, user_id) for user_id in ids]
        if active := [user for user in found if user.is_active]:
            return active
    return list(
        await db.scalars(select(User).where(User.role == Role.ADMIN, User.is_active.is_(True)))
    )


async def mark_paid(db: AsyncSession, user: User, task_id: int) -> Task:
    if user.role != Role.CLIENT:
        raise PaymentError(NOT_ALLOWED, 403)
    task = await _client_task(db, user, task_id)
    if task.status != TaskStatus.PLANNED:
        raise PaymentError("Статус уже изменён: обновите список", 409)
    _change(task, TaskStatus.PAID, user)
    audit.record(db, user.id, "task.mark_paid", "task", task.id)
    for recipient in await responsible(db, task.company_id):
        await enqueue(
            db,
            recipient.id,
            NotificationType.CLIENT_MARKED_PAID,
            tasks.today(),
            task.id,
            again=True,
        )
    await db.commit()
    return task


async def unmark_paid(db: AsyncSession, user: User, task_id: int) -> Task:
    """Клиент отменяет свою отметку; сотрудник — любую отметку клиента."""
    if user.role == Role.CLIENT:
        task = await _client_task(db, user, task_id)
        if not can_unmark(task, user, datetime.now(UTC)):
            raise PaymentError(
                "Отменить можно только свою отметку и только в отведённое время. "
                "Напишите бухгалтеру.",
                403,
            )
    elif user.role in EDITORS:
        task = await db.scalar(
            select(Task).where(Task.id == task_id, editable_task_condition(user)).with_for_update()
        )
        if task is None:
            raise not_found()
        if task.status != TaskStatus.PAID or task.status_changed_by_role != Role.CLIENT:
            raise PaymentError("Отметки клиента на этой задаче уже нет", 409)
    else:
        raise PaymentError("Недостаточно прав", 403)
    _change(task, TaskStatus.PLANNED, user)
    audit.record(db, user.id, "task.unmark_paid", "task", task.id)
    await db.commit()
    return task
