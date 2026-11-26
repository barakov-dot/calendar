"""Мониторинг: состояние бота, воркера, рассылки и резервных копий; сообщения администратору.

Бот и воркер следят друг за другом. Если остановлены оба или сервер, сообщить из
проекта некому — для этого нужна внешняя проверка /api/health/services.
"""

import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings_store import atomic_write
from app.models import Notification, NotificationStatus
from app.services.telegram.status import STALE_AFTER_SECONDS, read_status

logger = logging.getLogger(__name__)

CHECK_SECONDS = 60
# сбой должен продержаться столько, чтобы о нём сообщать: перезапуски не в счёт
GRACE_SECONDS = 180
SENDING_STALLED_SECONDS = 600
QUEUE_STUCK = timedelta(hours=2)
FAILURES_WINDOW = timedelta(hours=24)
BACKUP_MAX_AGE_SECONDS = 36 * 3600


def worker_status_path(settings_path: str | Path) -> Path:
    return Path(settings_path).with_name("worker_status.json")


class WorkerStatus:
    """Отметка «жив» воркера и время последнего успешного прохода рассылки."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self.path = path
        self._clock = clock
        self.sending_ok_at = clock()

    def sending_ok(self) -> None:
        self.sending_ok_at = self._clock()

    def save(self) -> None:
        data = {"updated_at": self._clock(), "sending_ok_at": self.sending_ok_at}
        try:
            atomic_write(self.path, json.dumps(data).encode())
        except OSError as error:
            logger.warning("Не удалось записать статус воркера: %s", error)


def read_worker(path: Path, now: float) -> dict | None:
    """None — файла нет или он давно не обновлялся."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        fresh = now - float(data["updated_at"]) <= STALE_AFTER_SECONDS
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return data if fresh else None


def worker_problems(path: Path, now: float) -> dict[str, str]:
    data = read_worker(path, now)
    if data is None:
        return {"worker_down": "Воркер не работает: напоминания и пересчёт задач остановлены"}
    if now - data.get("sending_ok_at", now) > SENDING_STALLED_SECONDS:
        return {"sending_stalled": "Рассылка не проходит: смотрите логи воркера"}
    return {}


def bot_problems(path: Path, now: float) -> dict[str, str]:
    status = read_status(path, now)
    state = status["state"]
    if state in ("unknown", "stopped"):
        return {"bot_down": "Бот не работает"}
    if state == "problem":
        return {"bot_problem": f"Бот не может подключиться: {status.get('problem')}"}
    if state == "unavailable":
        proxy = status.get("proxy") or "без прокси"
        return {"telegram": f"Telegram недоступен дольше 5 минут ({proxy}). Проверьте прокси"}
    return {}


async def sending_problems(db: AsyncSession, now: datetime) -> dict[str, str]:
    problems = {}
    failed = await db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.status == NotificationStatus.FAILED,
            Notification.created_at >= now - FAILURES_WINDOW,
            # блокировка бота пользователем — не сбой, она видна в карточке
            Notification.error.not_ilike("%blocked%"),
        )
    )
    if failed:
        problems["send_failures"] = f"Не доставлено сообщений за сутки: {failed}"
    stuck = await db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.status == NotificationStatus.PENDING,
            Notification.created_at < now - QUEUE_STUCK,
        )
    )
    if stuck:
        problems["queue_stuck"] = f"Сообщения ждут отправки больше двух часов: {stuck}"
    return problems


def backup_problems(directory: Path, now: float) -> dict[str, str]:
    newest = max((path.stat().st_mtime for path in directory.glob("buh-*.tar.gz")), default=None)
    if newest is None or now - newest > BACKUP_MAX_AGE_SECONDS:
        return {"backup": "Нет свежей резервной копии (старше 36 часов). Проверьте cron"}
    return {}


@dataclass
class _Problem:
    text: str
    since: float
    announced: bool = False
    undelivered: bool = False  # пытались сообщить, но Telegram не принял


class Alerter:
    """Сообщает о сбое один раз и ещё раз — о восстановлении.

    Если сообщить во время сбоя не удалось (например, не работал прокси),
    после восстановления приходит сообщение о том, что сбой был.
    """

    def __init__(
        self,
        send: Callable[[str], Awaitable[bool]],
        timezone: str = "Europe/Moscow",
        grace: float = GRACE_SECONDS,
    ) -> None:
        self._send = send
        self._timezone = timezone
        self._grace = grace
        self._problems: dict[str, _Problem] = {}

    def _time(self, moment: float) -> str:
        local = datetime.fromtimestamp(moment, UTC).astimezone(ZoneInfo(self._timezone))
        return f"{local:%d.%m %H:%M}"

    async def tick(self, current: dict[str, str], now: float) -> None:
        for key, text in current.items():
            problem = self._problems.setdefault(key, _Problem(text, now))
            problem.text = text
            if not problem.announced and now - problem.since >= self._grace:
                logger.warning("Сбой: %s", text)
                problem.announced = await self._send(f"⚠️ {text} (с {self._time(problem.since)})")
                problem.undelivered = not problem.announced

        for key in [key for key in self._problems if key not in current]:
            problem = self._problems[key]
            if problem.announced:
                message = f"✅ Восстановлено: {problem.text}"
            elif problem.undelivered:
                message = (
                    f"⚠️ Был сбой с {self._time(problem.since)} по {self._time(now)}: {problem.text}"
                )
            else:
                del self._problems[key]  # прошёл сам раньше срока
                continue
            if await self._send(message):
                del self._problems[key]
