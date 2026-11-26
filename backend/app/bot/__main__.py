"""Telegram-бот (long polling): python -m app.bot."""

import asyncio
import logging
import time

from app.bot.dispatcher import build_dispatcher
from app.bot.runner import BotRunner
from app.core.config import Config, get_config
from app.core.service import cancel, run_service
from app.core.settings_store import SettingsStore, get_store
from app.services.monitoring import CHECK_SECONDS, Alerter, worker_problems, worker_status_path
from app.services.telegram.admin import admin_sender
from app.services.telegram.client import TelegramClient


async def watch_worker(store: SettingsStore, config: Config, client: TelegramClient) -> None:
    """Бот сообщает администратору, если остановился воркер."""
    alerter = Alerter(admin_sender(client, config), store.get().company.timezone)
    path = worker_status_path(config.settings_path)
    while True:
        # первая проверка — после паузы: воркер мог только запускаться
        await asyncio.sleep(CHECK_SECONDS)
        try:
            await alerter.tick(worker_problems(path, time.time()), time.time())
        except Exception:
            logging.getLogger("bot").exception("Ошибка проверки воркера")


async def main(stop: asyncio.Event) -> None:
    config = get_config()
    store = get_store()
    runner = BotRunner(store, config, TelegramClient(store, config), build_dispatcher(store))
    watcher = asyncio.create_task(store.watch())
    monitor_client = TelegramClient(store, config)
    monitor = asyncio.create_task(watch_worker(store, config, monitor_client))
    try:
        await runner.run(stop)
    finally:
        await cancel(watcher, monitor)
        await monitor_client.close()


if __name__ == "__main__":
    run_service("bot", main)
