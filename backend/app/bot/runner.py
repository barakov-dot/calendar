"""Long polling с переподключением при смене прокси в настройках — без перезапуска."""

import asyncio
import logging
from collections.abc import Sequence

from aiogram import Bot, Dispatcher
from aiogram.utils.backoff import BackoffConfig
from aiogram.utils.token import TokenValidationError

from app.bot.menu import set_menu
from app.core.config import Config
from app.core.service import cancel, wait_any
from app.core.settings_store import SettingsStore
from app.services.telegram.client import TelegramClient
from app.services.telegram.connect import REQUEST_TIMEOUT, RETRY_DELAYS, with_retries
from app.services.telegram.factory import Proxy, ProxyConfigError
from app.services.telegram.status import BotStatus, status_path

logger = logging.getLogger(__name__)

POLLING_BACKOFF = BackoffConfig(min_delay=1, max_delay=30, factor=2, jitter=0.1)


class BotRunner:
    def __init__(
        self,
        store: SettingsStore,
        config: Config,
        client: TelegramClient,
        dispatcher: Dispatcher,
        retry_delays: Sequence[float] = RETRY_DELAYS,
        polling_timeout: int = 10,
        status: BotStatus | None = None,
        menu_interval: float = 5,
    ) -> None:
        self._store = store
        self._config = config
        self._client = client
        self._dispatcher = dispatcher
        self._retry_delays = retry_delays
        self._polling_timeout = polling_timeout
        self._menu_interval = menu_interval
        self._status = status or BotStatus(status_path(config.settings_path))
        self._changed = asyncio.Event()
        self._settings_error = asyncio.Event()

    async def run(self, stop: asyncio.Event) -> None:
        heartbeat = asyncio.create_task(self._status.heartbeat())
        try:
            await self._run(stop)
        finally:
            await cancel(heartbeat)

    async def _run(self, stop: asyncio.Event) -> None:
        if self._config.bot_token is None:
            logger.error(
                "BOT_TOKEN не задан: бот не подключается. Добавьте его в .env и перезапустите"
            )
            self._status.blocked("BOT_TOKEN не задан в .env")
            await stop.wait()
            return

        unsubscribe = (
            self._store.subscribe(lambda _: self._changed.set()),
            self._store.subscribe_errors(lambda _: self._settings_error.set()),
        )
        self._store.reload()
        if self._store.last_error:
            self._settings_error.set()
        try:
            while not stop.is_set():
                await self._run_connection(stop)
        finally:
            for remove in unsubscribe:
                remove()
            await self._client.close()

    async def _run_connection(self, stop: asyncio.Event) -> None:
        """Работает на одном прокси, пока тот не изменится или не придёт сигнал остановки."""
        self._changed.clear()
        try:
            proxy = self._client.current_proxy()
            bot = await self._client.get_bot()
        except ProxyConfigError as error:
            logger.error("%s", error)
            self._status.blocked(str(error))
            await wait_any(stop, self._changed)
            return
        except TokenValidationError:
            logger.error("BOT_TOKEN имеет неверный формат. Проверьте его в .env")
            self._status.blocked("BOT_TOKEN в .env имеет неверный формат")
            await stop.wait()
            return

        self._status.proxy = str(proxy) if proxy else None
        self._status.problem = None
        self._status.failing_since = None
        self._status.last_success_at = None
        bot.session.middleware(self._status.middleware())
        session = asyncio.create_task(self._serve(bot))
        reconfigured = asyncio.create_task(self._proxy_changed(proxy))
        stopped = asyncio.create_task(stop.wait())
        try:
            await asyncio.wait(
                (session, reconfigured, stopped), return_when=asyncio.FIRST_COMPLETED
            )
            if session.done() and session.exception() is not None:
                error = session.exception()
                logger.error("Polling прерван: %s: %s", type(error).__name__, error)
                await wait_any(stop, self._changed, seconds=self._retry_delays[0])
            elif reconfigured.done():
                logger.info("Настройки прокси изменились, переподключаемся")
        finally:
            await cancel(reconfigured, stopped)
            await self._stop_session(session)
            await self._client.close()

    async def _proxy_changed(self, current: Proxy | None) -> None:
        while True:
            await self._changed.wait()
            self._changed.clear()
            try:
                if self._client.current_proxy() != current:
                    return
            except ProxyConfigError:
                return

    async def _serve(self, bot: Bot) -> None:
        async def connect():
            await bot.delete_webhook(request_timeout=REQUEST_TIMEOUT)
            return await bot.me()

        me = await with_retries(connect, self._retry_delays)
        logger.info("Бот @%s подключён", me.username)
        self._status.username = me.username
        self._status.save()
        alerts = asyncio.create_task(self._send_alerts(bot))
        menu = asyncio.create_task(self._keep_menu(bot))
        try:
            await self._dispatcher.start_polling(
                bot,
                polling_timeout=self._polling_timeout,
                backoff_config=POLLING_BACKOFF,
                handle_signals=False,
                close_bot_session=False,
                tasks_shutdown_timeout=5,
            )
        finally:
            await cancel(alerts, menu)

    async def _keep_menu(self, bot: Bot) -> None:
        """Команды и кнопка меню Mini App; обновляются при смене адреса в настройках."""
        shown: str | None = None
        while True:
            url = self._store.get().telegram.mini_app_url
            if url != shown:
                try:
                    await set_menu(bot, url)
                    shown = url
                except Exception as error:
                    logger.warning(
                        "Не удалось настроить меню бота: %s: %s", type(error).__name__, error
                    )
            await asyncio.sleep(self._menu_interval)

    async def _stop_session(self, session: asyncio.Task) -> None:
        if not session.done():
            try:
                # Корректная остановка: отмена задачи оставила бы фоновый getUpdates.
                await self._dispatcher.stop_polling()
            except RuntimeError:
                session.cancel()  # polling ещё не начался
        await asyncio.wait((session,))
        if not session.cancelled():
            session.exception()  # уже записана в лог

    async def _send_alerts(self, bot: Bot) -> None:
        """Сообщает администратору о неприменённом файле настроек."""
        while True:
            await self._settings_error.wait()
            self._settings_error.clear()
            reason = self._store.last_error
            if reason is None or self._config.admin_telegram_id is None:
                continue
            try:
                await bot.send_message(
                    self._config.admin_telegram_id,
                    "⚠️ Файл настроек settings.json содержит ошибку и не применён. "
                    f"Работаем на последней рабочей версии.\n\n{reason}",
                    request_timeout=REQUEST_TIMEOUT,
                )
            except Exception as error:
                logger.warning(
                    "Не удалось уведомить администратора: %s: %s", type(error).__name__, error
                )
