import logging
from collections.abc import Awaitable, Callable

from app.core.config import Config
from app.services.telegram.client import TelegramClient
from app.services.telegram.connect import REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


def admin_sender(client: TelegramClient, config: Config) -> Callable[[str], Awaitable[bool]]:
    """Отправка сообщения администратору. False — не доставлено, стоит повторить."""

    async def send(text: str) -> bool:
        if config.bot_token is None or config.admin_telegram_id is None:
            return False
        try:
            bot = await client.get_bot()
            await bot.send_message(config.admin_telegram_id, text, request_timeout=REQUEST_TIMEOUT)
        except Exception as error:
            logger.warning("Не удалось уведомить администратора: %s", type(error).__name__)
            return False
        return True

    return send
