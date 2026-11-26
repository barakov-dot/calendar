"""Общий запуск фоновых сервисов (bot, worker)."""

import asyncio
import contextlib
import logging
import signal
from collections.abc import Awaitable, Callable

from app.core.logging import setup_logging

ServiceMain = Callable[[asyncio.Event], Awaitable[None]]


async def _serve(name: str, main: ServiceMain) -> None:
    logger = logging.getLogger(name)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    logger.info("Сервис %s запущен", name)
    await main(stop)
    logger.info("Сервис %s остановлен", name)


def run_service(name: str, main: ServiceMain) -> None:
    setup_logging()
    asyncio.run(_serve(name, main))


async def wait_any(*events: asyncio.Event, seconds: float | None = None) -> None:
    """Ждёт первое из событий, но не дольше seconds."""
    tasks = [asyncio.create_task(event.wait()) for event in events]
    try:
        await asyncio.wait(tasks, timeout=seconds, return_when=asyncio.FIRST_COMPLETED)
    finally:
        await cancel(*tasks)


async def cancel(*tasks: asyncio.Task) -> None:
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task
