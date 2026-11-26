"""Общий запуск фоновых сервисов (bot, worker)."""

import asyncio
import logging
import signal

from app.core.logging import setup_logging


async def run_idle(name: str, stop: asyncio.Event) -> None:
    """Заглушка: сообщает о запуске и ждёт сигнала остановки."""
    logger = logging.getLogger(name)
    logger.info("Сервис %s запущен (заглушка)", name)
    await stop.wait()
    logger.info("Сервис %s остановлен", name)


async def _serve(name: str) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    await run_idle(name, stop)


def run_service(name: str) -> None:
    setup_logging()
    asyncio.run(_serve(name))
