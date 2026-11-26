"""Проверка подключения к Telegram через указанный прокси, без сохранения настроек."""

import asyncio
import contextlib
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from aiogram.client.telegram import PRODUCTION, TelegramAPIServer
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.utils.token import TokenValidationError
from aiohttp_socks import ProxyConnectionError, ProxyError

from app.core.config import Config
from app.services.telegram.factory import Proxy, create_bot

PROXY_CONNECT_TIMEOUT = 5
REQUEST_TIMEOUT = 15

NO_PROXY_CONNECTION = "Нет соединения с прокси"
BAD_CREDENTIALS = "Неверный логин или пароль прокси"
TELEGRAM_BEHIND_PROXY = "Прокси отвечает, но Telegram недоступен"
TELEGRAM_UNAVAILABLE = "Telegram недоступен напрямую"


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    message: str
    latency_ms: int | None = None


async def _proxy_reachable(proxy: Proxy) -> bool:
    parts = urlsplit(proxy.url)
    try:
        async with asyncio.timeout(PROXY_CONNECT_TIMEOUT):
            _, writer = await asyncio.open_connection(parts.hostname, parts.port)
    except (OSError, TimeoutError, UnicodeError):
        return False
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return True


async def check_connection(
    config: Config,
    proxy: Proxy | None,
    api: TelegramAPIServer = PRODUCTION,
    request_timeout: int = REQUEST_TIMEOUT,
) -> CheckResult:
    if config.bot_token is None:
        return CheckResult(False, "BOT_TOKEN не задан в .env")
    if proxy is not None and not await _proxy_reachable(proxy):
        return CheckResult(False, NO_PROXY_CONNECTION)
    try:
        bot = create_bot(config, proxy, api)
    except TokenValidationError:
        return CheckResult(False, "BOT_TOKEN в .env имеет неверный формат")
    failure = TELEGRAM_BEHIND_PROXY if proxy else TELEGRAM_UNAVAILABLE
    try:
        started = time.monotonic()
        me = await bot.get_me(request_timeout=request_timeout)
        latency = round((time.monotonic() - started) * 1000)
    except TelegramUnauthorizedError:
        return CheckResult(False, "Telegram отклонил BOT_TOKEN из .env")
    except ProxyConnectionError:
        return CheckResult(False, NO_PROXY_CONNECTION)
    except ProxyError as error:
        return CheckResult(
            False, BAD_CREDENTIALS if "authentication" in str(error).lower() else failure
        )
    except Exception:
        # Текст исключения не возвращается: в нём могут быть технические подробности подключения.
        return CheckResult(False, failure)
    finally:
        await bot.session.close()
    return CheckResult(True, f"Бот @{me.username} доступен, задержка {latency} мс", latency)
