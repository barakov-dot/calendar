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
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import editable_task_condition, visible_task_condition
from app.core.settings_store import AppSettings
from app.models import (
    Company,
    CompanyMember,
    Notification,
    NotificationStatus,
    NotificationType,
    Role,
    Task,
    TaskKind,
    TaskStatus,
    User,
)
from app.services.notify import messages
from app.services.notify.planner import local_now
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


async def digest_tasks(
    db: AsyncSession, user: User, current: date
) -> list[tuple[Task, Company | None]]:
    """Открытые задачи компаний, за которые отвечает пользователь, и личные."""
    rows = await db.execute(
        select(Task, Company)
        .outerjoin(Company, Company.id == Task.company_id)
        .where(
            Task.status == TaskStatus.PLANNED,
            Task.due_date <= current + timedelta(days=7),
            or_(
                Task.owner_id == user.id,
                (Company.accountant_id == user.id) & Company.is_archived.is_(False),
            ),
        )
        .order_by(Task.due_date, Company.name, Task.title, Task.id)
    )
    return [(task, company) for task, company in rows]


async def _task_for(
    db: AsyncSession, settings: AppSettings, user: User, task_id: int
) -> tuple[Task, Company, CompanyMember | None] | None:
    """Задача, если получатель всё ещё вправе её видеть."""
    if user.role == Role.CLIENT:
        condition = visible_task_condition(user, settings.tasks.show_notices_to_clients)
    elif user.role in (Role.ADMIN, Role.ACCOUNTANT):
        condition = editable_task_condition(user)
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
    if row.scheduled_for != current or user.role not in (Role.ADMIN, Role.ACCOUNTANT):
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
        item = await _task_for(db, settings, user, row.task_id)
        if item is None or item[0].status != TaskStatus.PLANNED:
            continue
        task = item[0]
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


async def _single(
    db: AsyncSession, settings: AppSettings, user: User, row: Notification, current: date
) -> Message | None:
    item = await _task_for(db, settings, user, row.task_id)
    if item is None:
        return None
    task, company, member = item
    if row.type == NotificationType.CLIENT_MARKED_PAID:
        if task.status != TaskStatus.PAID or task.status_changed_by_role != Role.CLIENT:
            return None
        payer = await db.get(User, task.status_changed_by)
        name = f"{payer.first_name} {payer.last_name}".strip() or "Клиент"
        # оплата уже отмечена, поэтому без цветного кружка срочности
        line = (
            f"{messages.company_name(company)}: {task.title} (до {messages.short(task.due_date)})"
        )
        if task.amount_kopecks is not None:
            line += f" — {messages.money(task.amount_kopecks)}"
        text = f"{name} отметил(а) оплату\n{line}"
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
            result = await bot.send_message(
                user.telegram_id,
                message.text,
                reply_markup=message.keyboard,
                request_timeout=REQUEST_TIMEOUT,
            )
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
