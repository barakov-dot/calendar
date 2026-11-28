"""Когда пользователю пора присылать напоминания: в выбранное им время и в его поясе."""

from datetime import date, datetime, time
from typing import Literal, get_args
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings_store import AppSettings
from app.models import NotificationSettings
from app.services.notify.queue import enqueue

# часовые пояса России, от Калининграда до Камчатки
TimeZone = Literal[
    "Europe/Kaliningrad",
    "Europe/Moscow",
    "Europe/Samara",
    "Asia/Yekaterinburg",
    "Asia/Omsk",
    "Asia/Krasnoyarsk",
    "Asia/Irkutsk",
    "Asia/Yakutsk",
    "Asia/Vladivostok",
    "Asia/Magadan",
    "Asia/Kamchatka",
]
TIME_ZONES = get_args(TimeZone)
# позже этого времени по Москве напоминания дня уже не откладываются
LAST_MOMENT = time(23, 45)


class Clock:
    """Один проход планировщика: день — по времени компании, час — у каждого свой."""

    def __init__(
        self,
        settings: AppSettings,
        now: datetime,
        current: date,
        own: dict[int, tuple[str | None, str | None]],
    ) -> None:
        self.settings = settings
        self.now = now
        self.current = current
        self.own = own

    @classmethod
    async def load(
        cls, db: AsyncSession, settings: AppSettings, now: datetime, current: date
    ) -> "Clock":
        rows = await db.execute(
            select(
                NotificationSettings.user_id,
                NotificationSettings.digest_time,
                NotificationSettings.timezone,
            )
        )
        own = {user_id: (clock, zone) for user_id, clock, zone in rows}
        return cls(settings, now, current, own)

    def ready(self, user_id: int) -> bool:
        clock, zone = self.own.get(user_id, (None, None))
        business = ZoneInfo(self.settings.company.timezone)
        wanted = datetime.combine(
            self.current,
            time.fromisoformat(clock or self.settings.notifications.digest_time),
            ZoneInfo(zone) if zone else business,
        )
        # иначе поздний час в западном поясе наступал бы уже в следующий день и пропадал
        latest = datetime.combine(self.current, LAST_MOMENT, business)
        return self.now >= min(wanted, latest)

    async def put(
        self,
        db: AsyncSession,
        user_id: int,
        kind: str,
        scheduled_for: date,
        task_id: int | None = None,
    ) -> None:
        """Ставит в очередь, если у получателя уже наступило его время."""
        if self.ready(user_id):
            await enqueue(db, user_id, kind, scheduled_for, task_id)
