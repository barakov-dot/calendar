"""Планировщик рассылок: python -m app.worker. Задания появятся в Фазе 6.

Пока воркер только держит подключение к Telegram по актуальным настройкам и проверяет его.
"""

import asyncio
import logging
from collections.abc import Sequence

from aiogram import Bot
from aiogram.utils.token import TokenValidationError

from app.core.config import Config, get_config
from app.core.service import cancel, run_service, wait_any
from app.core.settings_store import SettingsStore, get_store
from app.services.telegram.client import TelegramClient
from app.services.telegram.connect import REQUEST_TIMEOUT, RETRY_DELAYS, with_retries
from app.services.telegram.factory import Proxy, ProxyConfigError

logger = logging.getLogger("worker")


async def run_worker(
    stop: asyncio.Event,
    store: SettingsStore,
    config: Config,
    client: TelegramClient,
    retry_delays: Sequence[float] = RETRY_DELAYS,
) -> None:
    if config.bot_token is None:
        logger.error("BOT_TOKEN не задан: рассылки невозможны. Добавьте его в .env и перезапустите")
        await stop.wait()
        return

    changed = asyncio.Event()
    unsubscribe = store.subscribe(lambda _: changed.set())
    active: Proxy | None = None
    check: asyncio.Task | None = None

    async def verify(bot: Bot) -> None:
        me = await with_retries(lambda: bot.get_me(request_timeout=REQUEST_TIMEOUT), retry_delays)
        logger.info("Telegram доступен, бот @%s", me.username)

    async def stop_check() -> None:
        nonlocal check
        if check is not None:
            await cancel(check)
            check = None

    try:
        while not stop.is_set():
            changed.clear()
            try:
                proxy = client.current_proxy()
                if check is None or proxy != active:
                    await stop_check()
                    check = asyncio.create_task(verify(await client.get_bot()))
                    active = proxy
            except ProxyConfigError as error:
                logger.error("%s", error)
                await stop_check()
            except TokenValidationError:
                logger.error("BOT_TOKEN имеет неверный формат. Проверьте его в .env")
                await stop.wait()
                break
            await wait_any(stop, changed)
    finally:
        unsubscribe()
        await stop_check()
        await client.close()


async def main(stop: asyncio.Event) -> None:
    config = get_config()
    store = get_store()
    watcher = asyncio.create_task(store.watch())
    try:
        await run_worker(stop, store, config, TelegramClient(store, config))
    finally:
        await cancel(watcher)


if __name__ == "__main__":
    run_service("worker", main)
