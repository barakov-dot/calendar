"""Telegram-бот (long polling): python -m app.bot."""

import asyncio

from app.bot.dispatcher import build_dispatcher
from app.bot.runner import BotRunner
from app.core.config import get_config
from app.core.service import cancel, run_service
from app.core.settings_store import get_store
from app.services.telegram.client import TelegramClient


async def main(stop: asyncio.Event) -> None:
    config = get_config()
    store = get_store()
    runner = BotRunner(store, config, TelegramClient(store, config), build_dispatcher(store))
    watcher = asyncio.create_task(store.watch())
    try:
        await runner.run(stop)
    finally:
        await cancel(watcher)


if __name__ == "__main__":
    run_service("bot", main)
