"""Повторы запросов к Telegram при ошибках сети и прокси."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence

from aiogram.exceptions import TelegramRetryAfter, TelegramUnauthorizedError

logger = logging.getLogger(__name__)

RETRY_DELAYS = (1, 2, 5, 10, 30)
REQUEST_TIMEOUT = 15


async def with_retries[T](
    action: Callable[[], Awaitable[T]], delays: Sequence[float] = RETRY_DELAYS
) -> T:
    """Повторяет action до успеха. Прерывается только отменой задачи."""
    attempt = 0
    while True:
        try:
            return await action()
        except TelegramRetryAfter as error:
            delay = error.retry_after
            logger.warning("Telegram просит подождать %s с", delay)
        except TelegramUnauthorizedError:
            delay = delays[-1]
            logger.error("Telegram отклонил BOT_TOKEN. Проверьте его в .env")
        except Exception as error:
            # Ошибки прокси aiogram не всегда оборачивает в TelegramNetworkError.
            delay = delays[min(attempt, len(delays) - 1)]
            logger.warning(
                "Нет связи с Telegram (%s: %s). Повтор через %s с",
                type(error).__name__,
                error,
                delay,
            )
        attempt += 1
        await asyncio.sleep(delay)
