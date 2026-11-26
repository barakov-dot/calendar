from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.core.config import Config

ACCESS_BY_INVITE = "Доступ по приглашению"
ADMIN_GREETING = "Бот платёжного календаря работает. Вы указаны администратором."


def build_router(config: Config) -> Router:
    router = Router()
    router.message.filter(F.chat.type == "private")

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        # Пользователи и приглашения появятся в Фазе 2.
        is_admin = (
            message.from_user is not None and message.from_user.id == config.admin_telegram_id
        )
        await message.answer(ADMIN_GREETING if is_admin else ACCESS_BY_INVITE)

    return router
