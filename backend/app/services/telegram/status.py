"""Статус бота для страницы настроек: bot пишет файл в общем каталоге config, api читает."""

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiogram import Bot

from app.core.logging import redact
from app.core.settings_store import atomic_write

logger = logging.getLogger(__name__)

UNAVAILABLE_AFTER_SECONDS = 300
HEARTBEAT_SECONDS = 5
# Без отметок дольше этого срока считаем, что процесс бота не работает.
STALE_AFTER_SECONDS = 60


def status_path(settings_path: str | Path) -> Path:
    return Path(settings_path).with_name("bot_status.json")


class BotStatus:
    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self.path = path
        self._clock = clock
        self.username: str | None = None
        self.proxy: str | None = None
        self.problem: str | None = None  # причина, по которой бот не может подключаться вовсе
        self.last_success_at: float | None = None
        self.failing_since: float | None = None
        self.last_error: str | None = None

    def success(self) -> None:
        self.last_success_at = self._clock()
        self.failing_since = None
        self.last_error = None
        self.problem = None

    def failure(self, error: str) -> None:
        if self.failing_since is None:
            self.failing_since = self._clock()
        self.last_error = error

    def middleware(self):
        """Отмечает результат каждого запроса к Telegram."""

        async def track(make_request, bot: Bot, method):
            try:
                result = await make_request(bot, method)
            except Exception as error:
                self.failure(f"{type(error).__name__}: {error}")
                raise
            self.success()
            return result

        return track

    def save(self) -> None:
        data = {
            "username": self.username,
            "proxy": self.proxy,
            "problem": self.problem,
            "last_success_at": self.last_success_at,
            "failing_since": self.failing_since,
            "last_error": redact(self.last_error) if self.last_error else None,
            "updated_at": self._clock(),
        }
        try:
            atomic_write(self.path, json.dumps(data, ensure_ascii=False).encode())
        except OSError as error:
            logger.warning("Не удалось записать статус бота: %s", error)


def read_status(path: Path, now: float | None = None) -> dict[str, Any]:
    """Состояние: unknown, stopped, problem, connecting, connected, error, unavailable."""
    now = time.time() if now is None else now
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        updated = float(data["updated_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return {"state": "unknown"}
    if now - updated > STALE_AFTER_SECONDS:
        state = "stopped"
    elif data.get("problem"):
        state = "problem"
    elif data.get("failing_since"):
        long = now - data["failing_since"] >= UNAVAILABLE_AFTER_SECONDS
        state = "unavailable" if long else "error"
    elif data.get("last_success_at"):
        state = "connected"
    else:
        state = "connecting"
    return data | {"state": state}
