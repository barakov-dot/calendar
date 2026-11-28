"""Отправка очереди. Перед отправкой сообщение составляется заново по текущим данным.

При недоступности Telegram или прокси сообщения остаются в очереди и уходят позже.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
)
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.core.permissions import editable_task_condition, visible_task_condition
from app.core.settings_store import AppSettings
from app.models import (
    EDITORS,
    Attachment,
    Broadcast,
    Company,
    CompanyMember,
    CompanyStaff,
    Demand,
    DemandStep,
    Notification,
    NotificationStatus,
    NotificationType,
    Role,
    Task,
    TaskKind,
    TaskStatus,
    User,
)
from app.services import staff, substitutions
from app.services.calendar.workdays import load_calendar
from app.services.demands import share
from app.services.demands.types import get_book
from app.services.notify import messages
from app.services.notify.planner import local_now, reachable, workdays_until
from app.services.task_state import before_start, before_start_condition
from app.services.telegram.connect import REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

BATCH = 100
# не более ~25 сообщений в секунду
PAUSE_SECONDS = 0.05
BACKOFF_SECONDS = (30, 60, 300, 900, 1800)
# эти уведомления бухгалтеру объединяются в одно сообщение
GROUPED = (NotificationType.FILL_AMOUNT, NotificationType.OVERDUE)


@dataclass
class Message:
    text: str
    keyboard: InlineKeyboardMarkup | None
    # строки очереди, вошедшие в сообщение
    rows: list[Notification]
    # (содержимое, имя файла): сообщение уходит подписью к документу
    document: tuple[bytes, str] | None = None


async def digest_tasks(
    db: AsyncSession, user: User, current: date
) -> list[tuple[Task, Company | None]]:
    """Открытые задачи компаний, за которые отвечает пользователь, и личные.

    Пока пользователя замещают, его компании получает замещающий.
    """
    replaced = await substitutions.active(db, current, *reachable())
    # помощник никого не замещает
    people = (
        {user.id} if user.role == Role.ASSISTANT else substitutions.answers_for(replaced, user.id)
    )
    own = staff.companies_of(CompanyStaff.user_id.in_(people))
    rows = await db.execute(
        select(Task, Company)
        .outerjoin(Company, Company.id == Task.company_id)
        .where(
            Task.status == TaskStatus.PLANNED,
            Task.due_date <= current + timedelta(days=7),
            ~before_start_condition(),
            or_(
                Task.owner_id == user.id,
                Company.id.in_(own) & Company.is_archived.is_(False),
            ),
        )
        .order_by(Task.due_date, Company.name, Task.title, Task.id)
    )
    return [(task, company) for task, company in rows]


def _assistant_wants(settings: AppSettings, user: User) -> bool:
    """Помощникам напоминания идут, только если это включено в настройках."""
    return user.role == Role.ASSISTANT and settings.notifications.assistant_reminders


async def _task_for(
    db: AsyncSession, settings: AppSettings, user: User, task_id: int, current: date
) -> tuple[Task, Company, CompanyMember | None] | None:
    """Задача, если получатель всё ещё вправе её видеть."""
    if user.role == Role.CLIENT:
        condition = visible_task_condition(user, settings.tasks.show_notices_to_clients, current)
    elif user.role in EDITORS:
        condition = editable_task_condition(user, current)
    elif _assistant_wants(settings, user):
        condition = visible_task_condition(user, settings.tasks.show_notices_to_clients, current)
    else:
        return None
    row = (
        await db.execute(
            select(Task, Company)
            .join(Company, Company.id == Task.company_id)
            .where(Task.id == task_id, condition, Company.is_archived.is_(False))
        )
    ).first()
    if row is None:
        return None
    return row[0], row[1], await db.get(CompanyMember, (row[1].id, user.id))


async def _digest(
    db: AsyncSession, settings: AppSettings, user: User, row: Notification, current: date
) -> Message | None:
    if row.scheduled_for != current or not (
        user.role in EDITORS or _assistant_wants(settings, user)
    ):
        return None
    header = f"Доброе утро! План на {messages.short(current)}"
    text = messages.overview(header, await digest_tasks(db, user, current), current)
    if text is None:
        return None
    return Message(text, messages.keyboard(messages.calendar_button(settings)), [row])


async def _grouped(
    db: AsyncSession,
    settings: AppSettings,
    user: User,
    rows: list[Notification],
    current: date,
) -> Message | None:
    kind = rows[0].type
    actual, found = [], []
    for row in rows:
        item = await _task_for(db, settings, user, row.task_id, current)
        if item is None or item[0].status != TaskStatus.PLANNED:
            continue
        task = item[0]
        # дату начала ведения могли указать, пока сообщение ждало отправки
        if before_start(task, item[1]):
            continue
        if kind == NotificationType.OVERDUE and task.due_date >= current:
            continue
        if kind == NotificationType.FILL_AMOUNT and (
            task.amount_kopecks is not None or task.due_date < current
        ):
            continue
        actual.append(row)
        found.append((task, item[1]))
    if not found:
        return None
    title = "Заполните сумму" if kind == NotificationType.FILL_AMOUNT else "Просрочено"
    path = f"tasks/{found[0][0].id}" if len(found) == 1 else ""
    return Message(
        messages.clip(messages.section(title, found, current)),
        messages.keyboard(messages.calendar_button(settings, path=path)),
        actual,
    )


async def _demand(
    db: AsyncSession, settings: AppSettings, user: User, row: Notification, current: date
) -> Message | None:
    """Напоминание о требовании: сотруднику — о любом шаге, клиенту — о сроке исполнения."""
    if user.role == Role.CLIENT:
        if not settings.notifications.demand_notify_clients:
            return None
        # задачи требований скрыты из календаря клиента, поэтому права проверяются отдельно
        found = (
            await db.execute(
                select(Task, Company)
                .join(Company, Company.id == Task.company_id)
                .join(CompanyMember, CompanyMember.company_id == Company.id)
                .where(
                    Task.id == row.task_id,
                    Task.demand_step == DemandStep.RESPONSE,
                    CompanyMember.user_id == user.id,
                    CompanyMember.receive_reminders.is_(True),
                    Company.is_archived.is_(False),
                )
            )
        ).first()
    else:
        found = await _task_for(db, settings, user, row.task_id, current)
    if found is None:
        return None
    task, company = found[0], found[1]
    if task.demand_id is None or task.status != TaskStatus.PLANNED or task.due_date < current:
        return None
    workdays = workdays_until(await load_calendar(db), current, task.due_date)
    buttons = messages.keyboard(
        messages.calendar_button(settings, "Открыть", f"demands/{task.demand_id}")
    )
    text = messages.demand_reminder(task, company, current, workdays)
    return Message(text, buttons, [row])


async def _demand_share(
    db: AsyncSession, settings: AppSettings, user: User, row: Notification
) -> Message | None:
    """Требование, отправленное вручную. Получатель всё ещё должен быть связан с компанией."""
    task = await db.get(Task, row.task_id)
    if task is None or task.demand_id is None:
        return None
    demand = await db.get(
        Demand, task.demand_id, options=[undefer(Demand.data)], populate_existing=True
    )
    company = await db.get(Company, demand.company_id)
    allowed = {item.user.id for item in await share.candidates(db, demand)}
    if user.id not in allowed or company.is_archived:
        return None
    kind = get_book().kind(demand.knd)
    text = messages.demand_share(demand, kind.name, kind.response_label, company, row.note)
    buttons = messages.keyboard(
        messages.calendar_button(settings, "Открыть", f"demands/{demand.id}")
    )
    if demand.data is None:
        return Message(messages.clip(text), buttons, [row])
    return Message(text[:1024], buttons, [row], (demand.data, demand.filename))


async def _single(
    db: AsyncSession, settings: AppSettings, user: User, row: Notification, current: date
) -> Message | None:
    if row.type == NotificationType.DEMAND:
        return await _demand(db, settings, user, row, current)
    if row.type == NotificationType.DEMAND_SHARE:
        return await _demand_share(db, settings, user, row)
    item = await _task_for(db, settings, user, row.task_id, current)
    if item is None:
        return None
    task, company, member = item
    if row.type == NotificationType.SIGNATURE:
        if task.status != TaskStatus.PLANNED or task.due_date < current:
            return None
        if user.role == Role.CLIENT and (member is None or not member.receive_reminders):
            return None
        buttons = messages.keyboard(
            messages.calendar_button(settings, "Открыть", f"tasks/{task.id}")
        )
        return Message(messages.signature_reminder(task, company, current), buttons, [row])
    if row.type == NotificationType.ATTACHMENT:
        author = await db.scalar(
            select(User)
            .join(Attachment, Attachment.uploaded_by == User.id)
            .where(Attachment.task_id == task.id, User.role == Role.CLIENT)
            .order_by(Attachment.id.desc())
            .limit(1)
        )
        if author is None or user.role == Role.CLIENT:
            return None  # файл уже удалили
        name = f"{author.first_name} {author.last_name}".strip() or "Клиент"
        text = f"{name} приложил(а) файл к платежу\n{messages.plain_line(task, company)}"
        buttons = messages.keyboard(
            messages.calendar_button(settings, "Открыть", f"tasks/{task.id}")
        )
        return Message(messages.clip(text), buttons, [row])
    if row.type == NotificationType.CLIENT_MARKED_PAID:
        if task.status != TaskStatus.PAID or task.status_changed_by_role != Role.CLIENT:
            return None
        payer = await db.get(User, task.status_changed_by)
        name = f"{payer.first_name} {payer.last_name}".strip() or "Клиент"
        text = f"{name} отметил(а) оплату\n{messages.plain_line(task, company)}"
        buttons = messages.keyboard(
            messages.calendar_button(settings, "Открыть", f"tasks/{task.id}"),
            messages.unpaid_button(task.id),
        )
        return Message(messages.clip(text), buttons, [row])

    # напоминание и просрочка клиенту
    if (
        member is None
        or not member.receive_reminders
        or task.status != TaskStatus.PLANNED
        or task.kind != TaskKind.PAYMENT
        or before_start(task, company)
    ):
        return None
    if row.type == NotificationType.REMINDER and task.due_date < current:
        return None
    if row.type == NotificationType.OVERDUE and (
        not member.can_mark_paid or task.due_date >= current
    ):
        return None
    buttons = messages.keyboard(
        messages.paid_button(task.id) if member.can_mark_paid else [],
        messages.calendar_button(settings),
    )
    return Message(messages.client_reminder(task, company, current), buttons, [row])


async def _compose(
    db: AsyncSession,
    settings: AppSettings,
    user: User,
    rows: list[Notification],
    current: date,
) -> Message | None:
    if not user.is_active or user.bot_blocked:
        return None
    if rows[0].type == NotificationType.BROADCAST:
        item = await db.get(Broadcast, rows[0].broadcast_id)
        return Message(item.text, None, [rows[0]])
    if rows[0].type == NotificationType.DIGEST:
        return await _digest(db, settings, user, rows[0], current)
    if rows[0].type in GROUPED and user.role != Role.CLIENT:
        return await _grouped(db, settings, user, rows, current)
    return await _single(db, settings, user, rows[0], current)


async def _next_group(db: AsyncSession, now: datetime) -> list[Notification]:
    due = or_(Notification.next_attempt_at.is_(None), Notification.next_attempt_at <= now)
    queue = (
        select(Notification)
        .where(Notification.status == NotificationStatus.PENDING, due)
        .with_for_update(skip_locked=True)
    )
    first = await db.scalar(queue.order_by(Notification.id).limit(1))
    if first is None or first.type not in GROUPED:
        return [] if first is None else [first]
    user = await db.get(User, first.user_id)
    if user.role == Role.CLIENT:
        return [first]
    return list(
        await db.scalars(
            queue.where(Notification.user_id == first.user_id, Notification.type == first.type)
            .order_by(Notification.id)
            .limit(BATCH)
        )
    )


def _finish(rows: list[Notification], status: str, error: str = "") -> None:
    for row in rows:
        row.status = status
        row.error = error[:1000]


def _postpone(rows: list[Notification], now: datetime, seconds: float, error: str) -> None:
    for row in rows:
        row.next_attempt_at = now + timedelta(seconds=seconds)
        row.error = error[:1000]


async def _transmit(bot: Bot, chat_id: int, message: Message):
    if message.document is None:
        return await bot.send_message(
            chat_id,
            message.text,
            reply_markup=message.keyboard,
            request_timeout=REQUEST_TIMEOUT,
        )
    data, filename = message.document
    return await bot.send_document(
        chat_id,
        BufferedInputFile(data, filename),
        caption=message.text,
        reply_markup=message.keyboard,
        # файл передаётся дольше обычного сообщения
        request_timeout=REQUEST_TIMEOUT * 3,
    )


async def deliver(
    db: AsyncSession,
    bot: Bot,
    settings: AppSettings,
    now: datetime,
    pause: float = PAUSE_SECONDS,
) -> int:
    """Отправляет готовые сообщения. Возвращает их число. Каждое — своя транзакция."""
    current = local_now(settings, now).date()
    sent = 0
    for _ in range(BATCH):
        rows = await _next_group(db, now)
        if not rows:
            break
        user = await db.get(User, rows[0].user_id, populate_existing=True)
        message = await _compose(db, settings, user, rows, current)
        if message is None:
            _finish(rows, NotificationStatus.SKIPPED)
            await db.commit()
            continue
        _finish([row for row in rows if row not in message.rows], NotificationStatus.SKIPPED)
        stop = False
        try:
            result = await _transmit(bot, user.telegram_id, message)
        except TelegramRetryAfter as error:
            _postpone(message.rows, now, error.retry_after, "Telegram просит подождать")
            stop = True
        except TelegramForbiddenError as error:
            user.bot_blocked = True
            _finish(message.rows, NotificationStatus.FAILED, str(error))
        except (TelegramBadRequest, TelegramNotFound) as error:
            logger.warning("Сообщение не принято Telegram: %s", error)
            _finish(message.rows, NotificationStatus.FAILED, str(error))
        except Exception as error:
            # сеть или прокси: ждём и повторяем, остальные пока не трогаем
            attempts = max(row.attempts for row in message.rows) + 1
            delay = BACKOFF_SECONDS[min(attempts, len(BACKOFF_SECONDS)) - 1]
            for row in message.rows:
                row.attempts = attempts
            _postpone(message.rows, now, delay, type(error).__name__)
            logger.warning("Нет связи с Telegram (%s), повтор позже", type(error).__name__)
            stop = True
        else:
            _finish(message.rows, NotificationStatus.SENT)
            for row in message.rows:
                row.sent_at = now
                row.telegram_message_id = result.message_id
            sent += 1
        await db.commit()
        if stop:
            break
        await asyncio.sleep(pause)
    return sent
