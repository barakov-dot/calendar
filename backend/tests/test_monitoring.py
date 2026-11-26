import json
import logging
import os
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import get_config
from app.core.logging import make_formatter
from app.healthcheck import healthy
from app.models import Notification, Role
from app.services import monitoring
from app.services.monitoring import (
    Alerter,
    WorkerStatus,
    backup_problems,
    bot_problems,
    sending_problems,
    worker_problems,
    worker_status_path,
)
from app.services.telegram.status import BotStatus, status_path
from tests.factories import make_user
from tests.fakes import TOKEN

NOW = 1_800_000_000.0


@pytest.fixture
def paths():
    settings = get_config().settings_path
    os.makedirs(os.path.dirname(settings), exist_ok=True)
    return status_path(settings), worker_status_path(settings)


def test_worker_state(paths):
    _, path = paths
    now = [NOW]
    assert "worker_down" in worker_problems(path, NOW)
    status = WorkerStatus(path, clock=lambda: now[0])
    status.save()
    assert worker_problems(path, NOW) == {}
    assert "worker_down" in worker_problems(path, NOW + 61)
    now[0] = NOW + 601  # процесс жив, но рассылка давно не проходила
    status.save()
    assert "sending_stalled" in worker_problems(path, now[0])
    status.sending_ok()
    status.save()
    assert worker_problems(path, now[0]) == {}


def test_bot_state(paths):
    path, _ = paths
    now = [NOW]
    assert "bot_down" in bot_problems(path, NOW)
    status = BotStatus(path, clock=lambda: now[0])
    status.proxy = "socks5://host:1"
    status.success()
    status.save()
    assert bot_problems(path, NOW) == {}
    status.failure("нет сети")
    now[0] = NOW + 301
    status.save()
    assert "прокси" in bot_problems(path, now[0])["telegram"]
    status.blocked("BOT_TOKEN не задан")
    assert "BOT_TOKEN" in bot_problems(path, now[0])["bot_problem"]


def test_healthcheck(paths):
    bot_path, worker_path = paths
    assert not healthy("bot", NOW) and not healthy("worker", NOW)
    bot = BotStatus(bot_path, clock=lambda: NOW)
    bot.failure("Telegram недоступен")
    bot.save()
    WorkerStatus(worker_path, clock=lambda: NOW).save()
    # без связи с Telegram процесс всё равно здоров
    assert healthy("bot", NOW) and healthy("worker", NOW)
    assert not healthy("bot", NOW + 100) and not healthy("worker", NOW + 100)


def test_backup_age(tmp_path):
    assert "backup" in backup_problems(tmp_path, NOW)
    copy = tmp_path / "buh-20260101-000000.tar.gz"
    copy.write_text("x")
    os.utime(copy, (NOW, NOW))
    assert backup_problems(tmp_path, NOW + 3600) == {}
    assert "backup" in backup_problems(tmp_path, NOW + 37 * 3600)


async def test_sending_problems(db):
    user = await make_user(db, 5, Role.CLIENT)
    now = datetime.now(UTC)

    def row(kind: str, status: str, error: str = "", age: timedelta = timedelta()):
        return Notification(
            user_id=user.id,
            type=kind,
            status=status,
            error=error,
            scheduled_for=now.date(),
            created_at=now - age,
        )

    db.add(row("digest", "failed", "Forbidden: bot was blocked by the user"))
    db.add(row("reminder", "pending", age=timedelta(minutes=5)))
    await db.commit()
    assert await sending_problems(db, now) == {}

    db.add(row("overdue", "failed", "chat not found"))
    db.add(row("fill_amount", "pending", age=timedelta(hours=3)))
    await db.commit()
    assert set(await sending_problems(db, now)) == {"send_failures", "queue_stuck"}


class Outbox:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.works = True

    async def __call__(self, text: str) -> bool:
        if self.works:
            self.sent.append(text)
        return self.works


PROBLEM = {"bot_down": "Бот не работает"}


async def test_alert_after_grace_once_and_recovery():
    outbox = Outbox()
    alerter = Alerter(outbox, grace=180)

    await alerter.tick(PROBLEM, NOW)
    await alerter.tick(PROBLEM, NOW + 100)
    assert outbox.sent == []
    await alerter.tick(PROBLEM, NOW + 200)
    await alerter.tick(PROBLEM, NOW + 300)
    assert len(outbox.sent) == 1 and outbox.sent[0].startswith("⚠️ Бот не работает (с ")
    await alerter.tick({}, NOW + 400)
    await alerter.tick({}, NOW + 500)
    assert outbox.sent[1:] == ["✅ Восстановлено: Бот не работает"]


async def test_short_glitch_is_silent():
    outbox = Outbox()
    alerter = Alerter(outbox, grace=180)

    await alerter.tick(PROBLEM, NOW)
    await alerter.tick({}, NOW + 60)

    assert outbox.sent == []


async def test_outage_reported_after_telegram_returns():
    outbox = Outbox()
    alerter = Alerter(outbox, grace=0)
    outbox.works = False
    await alerter.tick(PROBLEM, NOW)
    await alerter.tick({}, NOW + 600)  # восстановилось, но отправить ещё нельзя
    outbox.works = True

    await alerter.tick({}, NOW + 660)
    await alerter.tick({}, NOW + 720)

    assert len(outbox.sent) == 1
    assert "Был сбой с " in outbox.sent[0]


async def test_services_endpoint(client, paths):
    bot_path, worker_path = paths
    response = await client.get("/api/health/services")
    assert (response.status_code, response.json()) == (
        503,
        {"bot": "unknown", "worker": "down"},
    )
    bot = BotStatus(bot_path)
    bot.username, bot.proxy = "secret_bot", "socks5://host:1"
    bot.success()
    bot.save()
    WorkerStatus(worker_path).save()

    response = await client.get("/api/health/services")

    assert (response.status_code, response.json()) == (200, {"bot": "connected", "worker": "ok"})


def record(message: str, error: Exception | None = None) -> logging.LogRecord:
    info = (type(error), error, None) if error else None
    return logging.LogRecord("x", logging.ERROR, __file__, 1, message, (), info)


def test_json_logs_in_prod_are_redacted():
    line = make_formatter("prod").format(
        record(f"сбой /bot{TOKEN}/getMe\nвторая строка", OSError("socks5://u:pa55@h:1"))
    )

    data = json.loads(line)
    assert "\n" not in line
    assert data["level"] == "ERROR" and data["logger"] == "x"
    assert "вторая строка" in data["message"]
    assert "pa55" not in line and TOKEN.split(":")[1] not in line


def test_plain_logs_in_dev():
    assert not make_formatter("dev").format(record("привет")).startswith("{")
    assert monitoring.GRACE_SECONDS >= 60
