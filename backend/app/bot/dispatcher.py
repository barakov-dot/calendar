from collections import deque

from aiogram import Dispatcher
from aiogram.types import Update

from app.bot.handlers import build_router
from app.core.settings_store import SettingsStore

REMEMBERED_UPDATES = 1000


class SkipRepeatedUpdates:
    """После переподключения Telegram может прислать уже обработанные обновления ещё раз."""

    def __init__(self) -> None:
        self._order: deque[int] = deque(maxlen=REMEMBERED_UPDATES)
        self._seen: set[int] = set()

    async def __call__(self, handler, event: Update, data):
        if event.update_id in self._seen:
            return None
        if len(self._order) == self._order.maxlen:
            self._seen.discard(self._order[0])
        self._order.append(event.update_id)
        self._seen.add(event.update_id)
        return await handler(event, data)


def build_dispatcher(store: SettingsStore) -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.update.outer_middleware(SkipRepeatedUpdates())
    dispatcher.include_router(build_router(store))
    return dispatcher
