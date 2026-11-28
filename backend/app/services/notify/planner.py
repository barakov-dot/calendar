"""Решает, кому и о чём напомнить сегодня, и ставит это в очередь.

Повторные запуски безопасны: ключ в журнале не даёт создать дубль.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import client_task_condition
from app.core.settings_store import AppSettings
from app.models import (
    EDITORS,
    MANAGERS,
    ChangedBy,
    Company,
    CompanyMember,
    DemandStep,
    NotificationSettings,
    NotificationType,
    Role,
    Task,
    TaskKind,
    TaskStatus,
    User,
)
from app.services import staff as staff_service
from app.services import substitutions
from app.services.calendar.workdays import WorkCalendar, load_calendar
from app.services.notify.queue import enqueue
from app.services.task_state import PAYDAY_RULES, before_start_condition

# в это время дня квитанция по требованию считается подписанной
RECEIPT_SIGNED_AT = "17:00"
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
    roles = EDITORS
    if settings.notifications.assistant_reminders:
        roles = (*EDITORS, Role.ASSISTANT)
    rows = await db.execute(
        select(User.id, NotificationSettings.daily_digest, NotificationSettings.digest_time)
        .outerjoin(NotificationSettings, NotificationSettings.user_id == User.id)
        .where(User.role.in_(roles), *reachable())
    )
    for user_id, enabled, own_time in rows:
        if enabled is False or clock < (own_time or settings.notifications.digest_time):
            continue
        await enqueue(db, user_id, NotificationType.DIGEST, current)


def _open_company_tasks():
    return (
        select(Task, Company)
        .join(Company, Company.id == Task.company_id)
        .where(
            Task.status == TaskStatus.PLANNED,
            Company.is_archived.is_(False),
            ~before_start_condition(),
        )
    )


@dataclass
class _Staff:
    """Кто из сотрудников получает уведомления по компаниям сегодня."""

    teams: dict[int, staff_service.Team]
    substitutes: dict[int, list[int]]
    reachable: set[int]
    assistant_reminders: bool

    def recipients(self, company_id: int, assistants: bool = True) -> list[int]:
        """Бухгалтеры компании (или замещающие) и, если включено, её помощники."""
        team = self.teams.get(company_id, staff_service.Team())
        found = [
            user_id
            for accountant in team.accountants
            for user_id in substitutions.recipients(self.substitutes, accountant.id)
        ]
        if assistants and self.assistant_reminders:
            found += [user.id for user in team.assistants]
        return [user_id for user_id in dict.fromkeys(found) if user_id in self.reachable]


async def _staff(db: AsyncSession, settings: AppSettings, current: date) -> _Staff:
    roles = (*substitutions.STAFF, Role.ASSISTANT)
    ids = await db.scalars(select(User.id).where(User.role.in_(roles), *reachable()))
    # недоступный замещающий не отнимает сообщения у бухгалтера
    replaced = await substitutions.active(db, current, *reachable())
    return _Staff(
        await staff_service.teams(db),
        replaced,
        set(ids),
        settings.notifications.assistant_reminders,
    )


async def _fill_amount(
    db: AsyncSession,
    settings: AppSettings,
    staff: _Staff,
    calendar: WorkCalendar,
    current: date,
) -> None:
    ahead = settings.notifications.fill_amount_workdays_before
    rows = await db.execute(
        _open_company_tasks().where(
            Task.kind == TaskKind.PAYMENT,
            Task.needs_amount.is_(True),
            Task.amount_kopecks.is_(None),
            # с запасом на длинные праздники; точный отбор — по рабочим дням ниже
            Task.due_date.between(current, current + timedelta(days=ahead * 2 + 20)),
        )
    )
    for task, company in rows.all():
        if workdays_until(calendar, current, task.due_date) <= ahead:
            # помощник сумму вписать не может
            for user_id in staff.recipients(company.id, assistants=False):
                await enqueue(db, user_id, NotificationType.FILL_AMOUNT, task.due_date, task.id)


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
            ~before_start_condition(),
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
        if task.rule_code in PAYDAY_RULES:
            wanted = left == 0
        else:
            wanted = (left == 0 and on_day) or left in offsets
        if wanted:
            await enqueue(db, member.user_id, NotificationType.REMINDER, current, task.id)


async def _signatures(
    db: AsyncSession, settings: AppSettings, staff: _Staff, current: date
) -> None:
    """Напоминания об окончании ЭЦП: за каждый из порогов по одному разу.

    Если пройдено несколько порогов (подпись внесли поздно), берётся ближайший.
    """
    thresholds = sorted({0, *settings.notifications.signature_offsets_days})
    rows = await db.execute(
        _open_company_tasks().where(
            Task.signature_id.is_not(None),
            Task.due_date.between(current, current + timedelta(days=thresholds[-1])),
        )
    )
    for task, company in rows.all():
        left = (task.due_date - current).days
        threshold = next(days for days in thresholds if days >= left)
        users = staff.recipients(company.id)
        if task.client_visible:
            users += await db.scalars(
                select(User.id)
                .join(CompanyMember, CompanyMember.user_id == User.id)
                .where(
                    CompanyMember.company_id == company.id,
                    CompanyMember.receive_reminders.is_(True),
                    User.role == Role.CLIENT,
                    *reachable(),
                )
            )
        for user_id in users:
            await enqueue(
                db,
                user_id,
                NotificationType.SIGNATURE,
                task.due_date - timedelta(days=threshold),
                task.id,
            )


async def _demands(
    db: AsyncSession,
    settings: AppSettings,
    staff: _Staff,
    calendar: WorkCalendar,
    current: date,
) -> None:
    """Требования инспекции: свои пороги в рабочих днях для квитанции и для ответа.

    Если пройдено несколько порогов (требование загрузили поздно), берётся ближайший.
    """
    notifications = settings.notifications
    offsets = {
        DemandStep.RECEIPT: sorted(notifications.demand_receipt_offsets_days),
        DemandStep.RESPONSE: sorted(notifications.demand_response_offsets_days),
    }
    admins = []
    if notifications.demand_notify_admin:
        query = select(User.id).where(User.role.in_(MANAGERS), *reachable())
        admins = list(await db.scalars(query))
    rows = await db.execute(
        # 200 дней — с запасом: пороги не больше 60 рабочих дней
        _open_company_tasks().where(
            Task.demand_id.is_not(None),
            Task.due_date.between(current, current + timedelta(days=200)),
        )
    )
    for task, company in rows.all():
        left = workdays_until(calendar, current, task.due_date)
        threshold = next((days for days in offsets[task.demand_step] if days >= left), None)
        if threshold is None:
            continue
        recipients = {*staff.recipients(company.id), *admins}
        # клиент не подписывает квитанцию, ему напоминают только о сроке исполнения
        if notifications.demand_notify_clients and task.demand_step == DemandStep.RESPONSE:
            recipients |= set(
                await db.scalars(
                    select(User.id)
                    .join(CompanyMember, CompanyMember.user_id == User.id)
                    .where(
                        CompanyMember.company_id == company.id,
                        CompanyMember.receive_reminders.is_(True),
                        User.role == Role.CLIENT,
                        *reachable(),
                    )
                )
            )
        for user_id in recipients:
            await enqueue(
                db,
                user_id,
                NotificationType.DEMAND,
                task.due_date - timedelta(days=threshold),
                task.id,
            )


async def _overdue(db: AsyncSession, settings: AppSettings, staff: _Staff, current: date) -> None:
    window = Task.due_date.between(
        current - timedelta(days=OVERDUE_WINDOW_DAYS), current - timedelta(days=1)
    )
    # бухгалтеру — всегда, по всем задачам его компаний
    rows = await db.execute(_open_company_tasks().where(window))
    for task, company in rows.all():
        for user_id in staff.recipients(company.id):
            await enqueue(db, user_id, NotificationType.OVERDUE, task.due_date, task.id)
    # клиенту — только если он платит сам
    rows = await db.execute(
        _client_tasks(settings).where(
            window,
            CompanyMember.can_mark_paid.is_(True),
            or_(Task.rule_code.is_(None), Task.rule_code.not_in(PAYDAY_RULES)),
        )
    )
    for task, member, _ in rows.all():
        await enqueue(db, member.user_id, NotificationType.OVERDUE, task.due_date, task.id)


async def _sign_receipts(db: AsyncSession, current: date, clock: str) -> None:
    """Квитанция о приёме требования подписывается сама в срок: отмечаем это.

    Задачи, статус которых уже меняли люди, не трогаем: «Вернуть в план» остаётся в силе.
    """
    last = current if clock >= RECEIPT_SIGNED_AT else current - timedelta(days=1)
    rows = await db.scalars(
        select(Task)
        .where(
            Task.demand_step == DemandStep.RECEIPT,
            Task.status == TaskStatus.PLANNED,
            Task.status_changed_at.is_(None),
            Task.due_date <= last,
        )
        .with_for_update(skip_locked=True)
    )
    for task in rows:
        task.status = TaskStatus.DONE
        task.status_changed_by_role = ChangedBy.SYSTEM
        task.status_changed_at = datetime.now(UTC)


async def plan(db: AsyncSession, settings: AppSettings, now: datetime) -> None:
    moment = local_now(settings, now)
    current, clock = moment.date(), moment.strftime("%H:%M")
    calendar = await load_calendar(db)
    # до напоминаний: о подписанной квитанции сообщать уже нечего
    await _sign_receipts(db, current, clock)
    await db.flush()
    await _digests(db, settings, current, clock, calendar.is_workday(current))
    # остальное — не раньше общего времени дайджеста, чтобы не писать ночью
    if clock >= settings.notifications.digest_time:
        staff = await _staff(db, settings, current)
        await _fill_amount(db, settings, staff, calendar, current)
        await _reminders(db, settings, current)
        await _signatures(db, settings, staff, current)
        await _demands(db, settings, staff, calendar, current)
        if settings.notifications.overdue_notify:
            await _overdue(db, settings, staff, current)
    await db.commit()
