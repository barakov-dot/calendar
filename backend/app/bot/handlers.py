"""/start: приглашения, согласие на обработку ПДн, подтверждение входа на сайт.

До согласия о пользователе ничего не сохраняется.
"""

from datetime import UTC, datetime

from aiogram import Bot, F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.types import User as TelegramUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.core.settings_store import SettingsStore
from app.models import Company, Invite, InviteKind, Role, User
from app.services import invites, login, login_code
from app.services.users import can_sign_in, get_by_telegram_id

ACCESS_BY_INVITE = "Доступ по приглашению"
LOGIN_EXPIRED = "Запрос на вход устарел. Нажмите «Войти» на сайте ещё раз."
LOGIN_CONFIRMED = "Вход подтверждён. Вернитесь на сайт."
LOGIN_CANCELLED = "Вход отменён."
CODE_DENIED = "Код отменён: по нему войти нельзя."
CONSENT_TEXT = (
    "Чтобы пользоваться сервисом, нужно согласие на обработку персональных данных: "
    "имени, имени пользователя и идентификатора Telegram."
)
GREETINGS = {
    Role.ADMIN: "Бот платёжного календаря работает. Вы указаны администратором.",
    Role.CHIEF: "Вы подключены как главный бухгалтер. Календарь доступен на сайте.",
    Role.ACCOUNTANT: "Вы подключены как бухгалтер. Календарь доступен на сайте.",
    Role.ASSISTANT: "Вы подключены как помощник бухгалтера (только просмотр). Календарь на сайте.",
    Role.CLIENT: "Вы подключены. Здесь будут напоминания о платежах.",
}


def _button(text: str, **kwargs) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text=text, **kwargs)]


def _profile(user: TelegramUser) -> invites.TelegramProfile:
    return invites.TelegramProfile(
        telegram_id=user.id,
        first_name=user.first_name,
        last_name=user.last_name or "",
        username=user.username or "",
    )


async def _known_user(db: AsyncSession, telegram: TelegramUser) -> User | None:
    """Активный пользователь сервиса. Заодно обновляет имя, если согласие уже есть."""
    user = await get_by_telegram_id(db, telegram.id)
    if user is None or not user.is_active:
        return None
    if user.bot_blocked:  # пишет боту — значит, разблокировал
        user.bot_blocked = False
        await db.commit()
    if user.pd_consent_at is not None:
        invites.apply_profile(user, _profile(telegram))
        await db.commit()
    return user


async def _accepted_text(db: AsyncSession, token: str, user: User) -> str:
    invite = await db.scalar(select(Invite).where(Invite.token == token))
    if invite.kind != InviteKind.CLIENT:
        return GREETINGS[Role(user.role)]
    company = await db.get(Company, invite.company_id)
    name = company.short_name or company.name
    return f"Вы подключены к компании «{name}». Здесь будут напоминания о платежах."


def build_router(store: SettingsStore) -> Router:
    router = Router()
    router.message.filter(F.chat.type == "private")
    router.callback_query.filter(F.message.chat.type == "private")

    async def ask_consent(bot: Bot, chat_id: int, payload: str) -> None:
        rows = [_button("Согласен", callback_data=f"agree:{payload}")]
        if url := store.get().company.privacy_policy_url:
            rows.insert(0, _button("Политика обработки данных", url=url))
        await bot.send_message(
            chat_id, CONSENT_TEXT, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
        )

    async def ask_login(bot: Bot, db: AsyncSession, chat_id: int, nonce: str) -> None:
        if await login.find_active(db, nonce) is None:
            await bot.send_message(chat_id, LOGIN_EXPIRED)
            return
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                _button("Войти на сайт", callback_data=f"login:{nonce}"),
                _button("Это не я", callback_data="login-cancel"),
            ]
        )
        await bot.send_message(
            chat_id,
            f"Вход на сайт. Код: {login.comparison_code(nonce)}\n\n"
            "Подтверждайте, только если вы сами сейчас нажали «Войти» "
            "и видите на сайте этот же код.",
            reply_markup=keyboard,
        )

    @router.my_chat_member()
    async def blocked_or_unblocked(event: ChatMemberUpdated) -> None:
        """Пользователь заблокировал или разблокировал бота."""
        if event.chat.type != "private":
            return
        async with get_sessionmaker()() as db:
            user = await get_by_telegram_id(db, event.chat.id)
            if user is not None:
                user.bot_blocked = event.new_chat_member.status == "kicked"
                await db.commit()

    @router.message(CommandStart())
    async def start(message: Message, command: CommandObject, bot: Bot) -> None:
        telegram = message.from_user
        if telegram is None:
            return
        payload = command.args or ""
        async with get_sessionmaker()() as db:
            if payload.startswith(invites.DEEPLINK_PREFIX):
                token = payload.removeprefix(invites.DEEPLINK_PREFIX)
                try:
                    await invites.check(db, token, telegram.id)
                    if not can_sign_in(await _known_user(db, telegram)):
                        await ask_consent(bot, message.chat.id, payload)
                        return
                    user = await invites.accept(db, token, _profile(telegram))
                except invites.InviteError as error:
                    await message.answer(str(error))
                    return
                await message.answer(await _accepted_text(db, token, user))
                return

            user = await _known_user(db, telegram)
            if user is None:
                await message.answer(ACCESS_BY_INVITE)
            elif user.pd_consent_at is None:
                await ask_consent(bot, message.chat.id, payload[:50])
            elif payload.startswith(login.DEEPLINK_PREFIX):
                nonce = payload.removeprefix(login.DEEPLINK_PREFIX)
                await ask_login(bot, db, message.chat.id, nonce)
            else:
                await message.answer(GREETINGS[Role(user.role)])

    async def finish(callback: CallbackQuery, text: str) -> None:
        """Заменяет сообщение с кнопками итогом, чтобы их нельзя было нажать повторно."""
        await callback.answer()
        if isinstance(callback.message, Message):
            await callback.message.edit_text(text)

    @router.callback_query(F.data.startswith("agree:"))
    async def agree(callback: CallbackQuery, bot: Bot) -> None:
        telegram = callback.from_user
        payload = callback.data.removeprefix("agree:")
        async with get_sessionmaker()() as db:
            if payload.startswith(invites.DEEPLINK_PREFIX):
                token = payload.removeprefix(invites.DEEPLINK_PREFIX)
                try:
                    user = await invites.accept(db, token, _profile(telegram))
                except invites.InviteError as error:
                    await finish(callback, str(error))
                    return
                await finish(callback, await _accepted_text(db, token, user))
                return

            user = await _known_user(db, telegram)
            if user is None:
                await finish(callback, ACCESS_BY_INVITE)
                return
            if user.pd_consent_at is None:
                user.pd_consent_at = datetime.now(UTC)
                await db.commit()
                await _known_user(db, telegram)
            await finish(callback, GREETINGS[Role(user.role)])
            if payload.startswith(login.DEEPLINK_PREFIX):
                nonce = payload.removeprefix(login.DEEPLINK_PREFIX)
                await ask_login(bot, db, telegram.id, nonce)

    @router.callback_query(F.data.startswith("login:"))
    async def confirm_login(callback: CallbackQuery) -> None:
        async with get_sessionmaker()() as db:
            if not can_sign_in(await _known_user(db, callback.from_user)):
                await finish(callback, ACCESS_BY_INVITE)
                return
            nonce = callback.data.removeprefix("login:")
            confirmed = await login.confirm(db, nonce, callback.from_user.id)
        await finish(callback, LOGIN_CONFIRMED if confirmed else LOGIN_EXPIRED)

    @router.callback_query(F.data.startswith(login_code.DENY_PREFIX))
    async def deny_code(callback: CallbackQuery) -> None:
        raw = callback.data.removeprefix(login_code.DENY_PREFIX)
        async with get_sessionmaker()() as db:
            user = await _known_user(db, callback.from_user)
            if user is not None and raw.isdigit():
                await login_code.deny(db, int(raw), user.id)
        await finish(callback, CODE_DENIED)

    @router.callback_query(F.data == "login-cancel")
    async def cancel_login(callback: CallbackQuery) -> None:
        await finish(callback, LOGIN_CANCELLED)

    return router
