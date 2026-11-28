"""Планировщик: python -m app.worker.

Раз в сутки (и при запуске) пересчитывает задачи, шлёт напоминания и дайджесты.
Подключение к Telegram держится по актуальным настройкам.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from aiogram import Bot
from aiogram.utils.token import TokenValidationError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import Config, get_config
from app.core.db import get_sessionmaker
from app.core.service import cancel, run_service, wait_any
from app.core.settings_store import SettingsStore, get_store
from app.services.monitoring import (
    CHECK_SECONDS,
    Alerter,
    WorkerStatus,
    backup_problems,
    bot_problems,
    sending_problems,
    worker_status_path,
)
from app.services.notify.planner import plan
from app.services.notify.sender import deliver
from app.services.rosstat import client as rosstat
from app.services.rosstat import sync as rosstat_sync
from app.services.tasks import Result, regenerate_all, today
from app.services.telegram.admin import admin_sender
from app.services.telegram.client import TelegramClient
from app.services.telegram.connect import REQUEST_TIMEOUT, RETRY_DELAYS, with_retries
from app.services.telegram.factory import Proxy, ProxyConfigError
from app.services.telegram.status import HEARTBEAT_SECONDS, status_path

logger = logging.getLogger("worker")

GENERATION_HOUR = 3
PLAN_SECONDS = 60
ROSSTAT_RETRY = timedelta(hours=1)
SEND_SECONDS = 5
# Об отсутствии правил и календаря на следующий год напоминаем незадолго до его начала.
WARNING_AHEAD = timedelta(days=60)
# Одно и то же предупреждение повторяется администратору не чаще раза в неделю.
REPEAT_WARNING_AFTER = timedelta(days=7)
_sent: dict[str, datetime] = {}


def should_send(text: str, now: datetime) -> bool:
    previous = _sent.get(text)
    return previous is None or now - previous >= REPEAT_WARNING_AFTER


def warning_text(result: Result, current: date) -> str | None:
    """Что сообщить администратору после генерации."""
    lines = []
    soon = (current + WARNING_AHEAD).year
    if missing := sorted(
        year for year in result.missing_calendar_years if current.year <= year <= soon
    ):
        years = ", ".join(map(str, missing))
        lines.append(
            f"Нет производственного календаря на {years}: переносы считаются по пятидневке "
            "без праздников. Загрузите календарь на странице настроек."
        )
    if missing := sorted(year for year in result.missing_rule_years if year <= soon):
        years = ", ".join(map(str, missing))
        lines.append(f"Нет файла налоговых правил на {years}: задачи за эти периоды не созданы.")
    return "⚠️ " + "\n".join(lines) if lines else None


async def generate_and_report(client: TelegramClient, config: Config) -> None:
    try:
        async with get_sessionmaker()() as db:
            result = await regenerate_all(db)
        logger.info(
            "Задачи пересчитаны: создано %s, обновлено %s, удалено %s",
            result.created,
            result.updated,
            result.deleted,
        )
        text = warning_text(result, today())
        if text is None:
            return
        logger.warning("%s", text)
        now = datetime.now(UTC)
        if not should_send(text, now):
            return
        if config.bot_token is not None and config.admin_telegram_id is not None:
            bot = await client.get_bot()
            await bot.send_message(config.admin_telegram_id, text, request_timeout=REQUEST_TIMEOUT)
            _sent[text] = now
    except Exception:
        logger.exception("Ошибка ежедневной генерации задач")


async def heartbeat(status: WorkerStatus) -> None:
    while True:
        status.save()
        await asyncio.sleep(HEARTBEAT_SECONDS)


async def run_monitor(store: SettingsStore, config: Config, client: TelegramClient) -> None:
    """Следит за ботом, очередью и резервными копиями."""
    alerter = Alerter(admin_sender(client, config), store.get().company.timezone)
    while True:
        try:
            now = time.time()
            problems = bot_problems(status_path(config.settings_path), now)
            async with get_sessionmaker()() as db:
                problems |= await sending_problems(db, datetime.now(UTC))
            if not config.is_dev:
                wanted = store.get().notifications.backup_alert
                problems |= backup_problems(Path(config.backups_path), now, wanted)
            await alerter.tick(problems, now)
        except Exception:
            logger.exception("Ошибка мониторинга")
        await asyncio.sleep(CHECK_SECONDS)


async def run_notifications(
    stop: asyncio.Event,
    store: SettingsStore,
    config: Config,
    client: TelegramClient,
    plan_every: float = PLAN_SECONDS,
    send_every: float = SEND_SECONDS,
    status: WorkerStatus | None = None,
) -> None:
    """Планирует напоминания и отправляет очередь."""
    if config.bot_token is None:
        return
    next_plan = 0.0
    loop = asyncio.get_running_loop()
    while not stop.is_set():
        try:
            settings = store.get()
            async with get_sessionmaker()() as db:
                if loop.time() >= next_plan:
                    await plan(db, settings, datetime.now(UTC))
                    next_plan = loop.time() + plan_every
                await deliver(db, await client.get_bot(), settings, datetime.now(UTC))
            if status is not None:
                status.sending_ok()
        except ProxyConfigError as error:
            logger.error("%s", error)
        except Exception:
            logger.exception("Ошибка рассылки уведомлений")
        await wait_any(stop, seconds=send_every)


async def run_telegram_check(
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


async def run_rosstat(stop: asyncio.Event, store: SettingsStore) -> None:
    """Раз в сутки в заданное время обновляет формы Росстата; новые компании — сразу."""
    retry_after = datetime.min.replace(tzinfo=UTC)
    while not stop.is_set():
        settings = store.get()
        now = datetime.now(UTC)
        if settings.rosstat.enabled and now >= retry_after:
            try:
                async with get_sessionmaker()() as db:
                    async with rosstat.Client(settings.rosstat.timeout_seconds) as client:
                        count = await rosstat_sync.run_due(db, settings, now, client)
                if count:
                    logger.info("Формы Росстата обновлены: организаций %s", count)
            except rosstat.Unavailable as error:
                logger.warning("Росстат недоступен (%s), повтор через час", error)
                retry_after = now + ROSSTAT_RETRY
            except Exception:
                logger.exception("Не удалось обновить формы Росстата")
                retry_after = now + ROSSTAT_RETRY
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), PLAN_SECONDS)


async def main(stop: asyncio.Event) -> None:
    config = get_config()
    store = get_store()
    client = TelegramClient(store, config)
    # свой клиент для сообщений администратору: проверка связи пересоздаёт свой
    alerts = TelegramClient(store, config)
    scheduler = AsyncIOScheduler(timezone=store.get().company.timezone)
    scheduler.add_job(
        generate_and_report,
        CronTrigger(hour=GENERATION_HOUR, timezone=store.get().company.timezone),
        args=(alerts, config),
        misfire_grace_time=3600,
        coalesce=True,
    )
    scheduler.start()
    watcher = asyncio.create_task(store.watch())
    initial = asyncio.create_task(generate_and_report(alerts, config))
    sender = TelegramClient(store, config)
    status = WorkerStatus(worker_status_path(config.settings_path))
    background = [
        asyncio.create_task(heartbeat(status)),
        asyncio.create_task(run_notifications(stop, store, config, sender, status=status)),
        asyncio.create_task(run_monitor(store, config, alerts)),
        asyncio.create_task(run_rosstat(stop, store)),
    ]
    try:
        await run_telegram_check(stop, store, config, client)
    finally:
        scheduler.shutdown(wait=False)
        await cancel(watcher, initial, *background)
        await alerts.close()
        await sender.close()


if __name__ == "__main__":
    run_service("worker", main)
