"""Bot, который пересоздаётся при смене прокси в настройках."""

import logging

from aiogram import Bot
from aiogram.client.telegram import PRODUCTION, TelegramAPIServer

from app.core.config import Config
from app.core.settings_store import SettingsStore
from app.services.telegram.factory import Proxy, create_bot, resolve_proxy

logger = logging.getLogger(__name__)


class TelegramClient:
    def __init__(
        self, store: SettingsStore, config: Config, api: TelegramAPIServer = PRODUCTION
    ) -> None:
        self._store = store
        self._config = config
        self._api = api
        self._bot: Bot | None = None
        self._proxy: Proxy | None = None

    def current_proxy(self) -> Proxy | None:
        """Прокси по текущим настройкам. Бросает ProxyConfigError."""
        return resolve_proxy(self._store.get(), self._config.telegram_proxy_url)

    async def get_bot(self) -> Bot:
        """Тот же объект, пока прокси не изменился."""
        proxy = self.current_proxy()
        if self._bot is None or proxy != self._proxy:
            await self.close()
            self._bot = create_bot(self._config, proxy, self._api)
            self._proxy = proxy
            logger.info("Подключение к Telegram: %s", proxy or "напрямую, без прокси")
        return self._bot

    async def close(self) -> None:
        if self._bot is not None:
            bot, self._bot = self._bot, None
            await bot.session.close()
