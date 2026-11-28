"""Сообщение пользователю, отправляемое сразу, минуя очередь (например, код входа)."""

import logging

from aiogram.types import InlineKeyboardMarkup

from app.core.config import get_config
from app.core.settings_store import get_store
from app.services.telegram.client import TelegramClient
from app.services.telegram.connect import REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


async def send_text(chat_id: int, text: str, keyboard: InlineKeyboardMarkup | None = None) -> None:
    """Ошибка только записывается в лог, без текста сообщения."""
    config = get_config()
    if config.bot_token is None:
        logger.warning("Сообщение не отправлено: BOT_TOKEN не задан")
        return
    client = TelegramClient(get_store(), config)
    try:
        bot = await client.get_bot()
        await bot.send_message(
            chat_id, text, reply_markup=keyboard, request_timeout=REQUEST_TIMEOUT
        )
    except Exception as error:
        logger.warning("Сообщение не отправлено: %s", type(error).__name__)
    finally:
        await client.close()
