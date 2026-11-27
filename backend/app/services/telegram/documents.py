"""Отправка файла пользователю в личный чат с ботом (в Mini App скачивание неудобно)."""

import logging

from aiogram.types import BufferedInputFile

from app.core.config import get_config
from app.core.settings_store import get_store
from app.models import User
from app.services.telegram.client import TelegramClient
from app.services.telegram.connect import REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


class SendError(Exception):
    """Текст показывается пользователю."""


async def send_document(user: User, data: bytes, filename: str, caption: str = "") -> None:
    config = get_config()
    if config.bot_token is None or user.telegram_id <= 0:
        raise SendError("Отправка в Telegram недоступна для этого пользователя")
    client = TelegramClient(get_store(), config)
    try:
        bot = await client.get_bot()
        await bot.send_document(
            user.telegram_id,
            BufferedInputFile(data, filename),
            caption=caption[:1000] or None,
            request_timeout=REQUEST_TIMEOUT * 3,
        )
    except Exception as error:
        logger.warning("Файл не отправлен в Telegram: %s", type(error).__name__)
        raise SendError("Не удалось отправить файл в Telegram. Попробуйте позже") from None
    finally:
        await client.close()
