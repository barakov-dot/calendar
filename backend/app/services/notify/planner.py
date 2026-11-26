"""Решает, кому и о чём напомнить сегодня, и ставит это в очередь.

Повторные запуски безопасны: ключ в журнале не даёт создать дубль.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import client_task_condition
from app.core.settings_store import AppSettings
from app.models import (
    Company,
    CompanyMember,
    NotificationSettings,
    NotificationType,
    Role,
    Task,
    TaskKind,
    TaskStatus,
    User,
)
from app.services.calendar.workdays import WorkCalendar, load_calendar
from app.services.notify.queue import enqueue

# Просрочку сообщаем по свежим срокам: старый долг не должен сыпаться пачкой.
OVERDUE_WINDOW_DAYS = 3


def local_now(settings: AppSettings, now: datetime) -> datetime:
    return now.astimezone(ZoneInfo(settings.company.timezone))


def workdays_until(calendar: WorkCalendar, current: date, due: date) -> int:
    """Рабочие дни после сегодняшнего, до срока включительно."""
    days = (due - current).days
    return sum(calendar.is_workday(current + timedelta(days=n)) for n in range(1, days + 1))


def reachable(user: type[User] = User):
    """Пользователи, которым можно писать. Тестовые (отрицательный id) не в счёт."""
    return (
        user.is_active.is_(True),
        user.bot_blocked.is_(False),
        user.pd_consent_at.is_not(None),
        user.telegram_id > 0,
    )


async def _digests(
    db: AsyncSession, settings: AppSettings, current: date, clock: str, workday: bool
) -> None:
    if settings.notifications.digest_workdays_only and not workday:
        return
    rows = await db.execute(
        select(User.id, NotificationSettings.daily_digest, NotificationSettings.digest_time)
        .outerjoin(NotificationSettings, NotificationSettings.user_id == User.id)
        .where(User.role.in_((Role.ADMIN, Role.ACCOUNTANT)), *reachable())
    )
    for user_id, enabled, own_time in rows:
        if enabled is False or clock < (own_time or settings.notifications.digest_time):
            continue
        await enqueue(db, user_id, NotificationType.DIGEST, current)


def _open_company_tasks():
    return (
        select(Task, Company)
        .join(Company, Company.id == Task.company_id)
        .where(Task.status == TaskStatus.PLANNED, Company.is_archived.is_(False))
    )


async def _fill_amount(
    db: AsyncSession, settings: AppSettings, calendar: WorkCalendar, current: date
) -> None:
    ahead = settings.notifications.fill_amount_workdays_before
    rows = await db.execute(
        _open_company_tasks()
        .join(User, User.id == Company.accountant_id)
        .where(
            Task.kind == TaskKind.PAYMENT,
            Task.needs_amount.is_(True),
            Task.amount_kopecks.is_(None),
            # с запасом на длинные праздники; точный отбор — по рабочим дням ниже
            Task.due_date.between(current, current + timedelta(days=ahead * 2 + 20)),
            *reachable(),
        )
    )
    for task, company in rows.all():
        if workdays_until(calendar, current, task.due_date) <= ahead:
            await enqueue(
                db, company.accountant_id, NotificationType.FILL_AMOUNT, task.due_date, task.id
            )


def _client_tasks(settings: AppSettings):
    """Платежи, о которых можно писать клиенту, вместе с его привязкой."""
    return (
        select(Task, CompanyMember, NotificationSettings)
        .join(Company, Company.id == Task.company_id)
        .join(CompanyMember, CompanyMember.company_id == Company.id)
        .join(User, User.id == CompanyMember.user_id)
        .outerjoin(NotificationSettings, NotificationSettings.user_id == User.id)
        .where(
            Task.status == TaskStatus.PLANNED,
            Task.kind == TaskKind.PAYMENT,
            client_task_condition(settings.tasks.show_notices_to_clients),
            Company.is_archived.is_(False),
            CompanyMember.receive_reminders.is_(True),
            User.role == Role.CLIENT,
            *reachable(),
        )
    )


async def _reminders(db: AsyncSession, settings: AppSettings, current: date) -> None:
    rows = await db.execute(
        _client_tasks(settings).where(Task.due_date.between(current, current + timedelta(days=365)))
    )
    defaults = settings.notifications
    for task, member, own in rows.all():
        offsets = (
            own.offsets_days
            if own is not None and own.offsets_days is not None
            else defaults.default_client_offsets_days
        )
        on_day = (
            own.on_due_day
            if own is not None and own.on_due_day is not None
            else defaults.remind_on_due_day
        )
        left = (task.due_date - current).days
        if (left == 0 and on_day) or left in offsets:
            await enqueue(db, member.user_id, NotificationType.REMINDER, current, task.id)


async def _overdue(db: AsyncSession, settings: AppSettings, current: date) -> None:
    window = Task.due_date.between(
        current - timedelta(days=OVERDUE_WINDOW_DAYS), current - timedelta(days=1)
    )
    # бухгалтеру — всегда, по всем задачам его компаний
    rows = await db.execute(
        _open_company_tasks()
        .join(User, User.id == Company.accountant_id)
        .where(window, *reachable())
    )
    for task, company in rows.all():
        await enqueue(db, company.accountant_id, NotificationType.OVERDUE, task.due_date, task.id)
    # клиенту — только если он платит сам
    rows = await db.execute(
        _client_tasks(settings).where(window, CompanyMember.can_mark_paid.is_(True))
    )
    for task, member, _ in rows.all():
        await enqueue(db, member.user_id, NotificationType.OVERDUE, task.due_date, task.id)


async def plan(db: AsyncSession, settings: AppSettings, now: datetime) -> None:
    moment = local_now(settings, now)
    current, clock = moment.date(), moment.strftime("%H:%M")
    calendar = await load_calendar(db)
    await _digests(db, settings, current, clock, calendar.is_workday(current))
    # остальное — не раньше общего времени дайджеста, чтобы не писать ночью
    if clock >= settings.notifications.digest_time:
        await _fill_amount(db, settings, calendar, current)
        await _reminders(db, settings, current)
        if settings.notifications.overdue_notify:
            await _overdue(db, settings, current)
    await db.commit()
