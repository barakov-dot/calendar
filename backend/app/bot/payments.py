"""Кнопки «Оплатил» и «Отменить отметку», команды /today и /week."""

from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.core.permissions import visible_task_condition
from app.core.settings_store import SettingsStore
from app.models import Company, Role, Task, TaskKind, TaskStatus
from app.services import payments, tasks
from app.services.notify import messages
from app.services.task_state import before_start_condition
from app.services.users import can_sign_in, get_by_telegram_id

ACCESS_BY_INVITE = "Доступ по приглашению"
NOTHING = "На этот период открытых задач нет."
MARKED = "✓ Отмечено: оплачено"
UNMARKED = "Отметка отменена, платёж снова ждёт оплаты"


def build_router(store: SettingsStore) -> Router:
    router = Router()
    router.message.filter(F.chat.type == "private")
    router.callback_query.filter(F.message.chat.type == "private")

    async def overview(message: Message, days: int, title: str) -> None:
        async with get_sessionmaker()() as db:
            user = await get_by_telegram_id(db, message.from_user.id) if message.from_user else None
            if not can_sign_in(user):
                await message.answer(ACCESS_BY_INVITE)
                return
            current = tasks.today()
            query = (
                select(Task, Company)
                .outerjoin(Company, Company.id == Task.company_id)
                .where(
                    visible_task_condition(user, store.get().tasks.show_notices_to_clients),
                    Task.status == TaskStatus.PLANNED,
                    Task.due_date <= current + timedelta(days=days),
                    # сроки до начала ведения календаря не пропущенные и не напоминают о себе
                    ~before_start_condition(),
                    Company.is_archived.is_(False) | Task.company_id.is_(None),
                )
                .order_by(Task.due_date, Company.name, Task.title, Task.id)
            )
            if user.role == Role.CLIENT:
                # клиенту — только платежи, прошлые долги показывает приложение
                query = query.where(Task.kind == TaskKind.PAYMENT, Task.due_date >= current)
            rows = [(task, company) for task, company in await db.execute(query)]
        text = messages.overview(f"{title} на {messages.short(current)}", rows, current)
        await message.answer(
            text or NOTHING,
            reply_markup=messages.keyboard(messages.calendar_button(store.get())),
        )

    @router.message(Command("today"))
    async def today(message: Message) -> None:
        await overview(message, 0, "Сегодня")

    @router.message(Command("week"))
    async def week(message: Message) -> None:
        await overview(message, 7, "Неделя")

    async def act(callback: CallbackQuery, action, note: str) -> None:
        task_id = callback.data.split(":", 1)[1]
        async with get_sessionmaker()() as db:
            user = await get_by_telegram_id(db, callback.from_user.id)
            if not can_sign_in(user) or not task_id.isdigit():
                await callback.answer(ACCESS_BY_INVITE, show_alert=True)
                return
            try:
                await action(db, user, int(task_id))
            except payments.PaymentError as error:
                await callback.answer(str(error), show_alert=True)
                return
        await callback.answer(note)
        if isinstance(callback.message, Message):
            # кнопки убираются, чтобы действие не повторили по ошибке
            await callback.message.edit_text(f"{callback.message.text}\n\n{note}")

    @router.callback_query(F.data.startswith("paid:"))
    async def paid(callback: CallbackQuery) -> None:
        await act(callback, payments.mark_paid, MARKED)

    @router.callback_query(F.data.startswith("unpaid:"))
    async def unpaid(callback: CallbackQuery) -> None:
        await act(callback, payments.unmark_paid, UNMARKED)

    return router
