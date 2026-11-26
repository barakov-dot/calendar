import asyncio
import contextlib
import logging

import pytest

from app.bot.dispatcher import build_dispatcher
from app.bot.handlers import ACCESS_BY_INVITE, GREETINGS
from app.bot.runner import BotRunner
from app.core.config import Config
from app.core.settings_store import SettingsStore
from app.models import Role, Task
from app.services.telegram.client import TelegramClient
from app.services.telegram.status import read_status, status_path
from app.worker import run_telegram_check
from tests.factories import make_user
from tests.fakes import PROXIED_HOST, TOKEN, FakeSocks5, FakeTelegram, eventually

ADMIN_ID = 111
STRANGER_ID = 222
FAST_RETRIES = (0.02,)


@pytest.fixture
def store(tmp_path):
    store = SettingsStore(tmp_path / "settings.json", check_interval=0)
    store.ensure_file()
    store.reload()
    return store


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", TOKEN)
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", str(ADMIN_ID))
    return Config()


def use_proxy(store, port: int) -> None:
    store.update({"telegram": {"proxy": {"enabled": True, "host": "127.0.0.1", "port": port}}})


@contextlib.asynccontextmanager
async def running(coroutine_factory, store):
    stop = asyncio.Event()
    watcher = asyncio.create_task(store.watch(interval=0.02))
    service = asyncio.create_task(coroutine_factory(stop))
    try:
        yield service
    finally:
        stop.set()
        try:
            await asyncio.wait_for(service, timeout=5)
        finally:
            watcher.cancel()


def bot_service(store, config, telegram):
    client = TelegramClient(store, config, telegram.api())
    runner = BotRunner(
        store, config, client, build_dispatcher(store), FAST_RETRIES, polling_timeout=0
    )
    return running(runner.run, store)


async def test_start_replies(store, config, db):
    await make_user(db, ADMIN_ID, Role.ADMIN)
    async with FakeTelegram() as telegram, FakeSocks5() as socks:
        use_proxy(store, socks.port)
        async with bot_service(store, config, telegram):
            telegram.send_start(1, STRANGER_ID)
            telegram.send_start(2, ADMIN_ID)
            await eventually(lambda: len(telegram.sent) == 2)

    assert sorted(telegram.sent) == [
        (ADMIN_ID, GREETINGS[Role.ADMIN]),
        (STRANGER_ID, ACCESS_BY_INVITE),
    ]
    assert telegram.calls.index("deleteWebhook") < telegram.calls.index("getUpdates")
    assert set(socks.targets) == {PROXIED_HOST}


async def test_manual_proxy_change_reconnects_without_restart(store, config):
    async with FakeTelegram() as telegram, FakeSocks5() as first, FakeSocks5() as second:
        use_proxy(store, first.port)
        async with bot_service(store, config, telegram) as service:
            telegram.send_start(1, STRANGER_ID)
            await eventually(lambda: len(telegram.sent) == 1)
            assert second.targets == []

            # правка файла «руками», мимо store.update
            text = store.path.read_text().replace(str(first.port), str(second.port))
            store.path.write_text(text)
            await eventually(lambda: second.targets)

            telegram.send_start(2, STRANGER_ID)
            await eventually(lambda: len(telegram.sent) == 2)
            await asyncio.sleep(0.1)
            assert not service.done()

    # обновление 1 пришло повторно после переподключения, но ответ на него один
    assert len(telegram.sent) == 2


async def test_unrelated_change_does_not_reconnect(store, config):
    async with FakeTelegram() as telegram, FakeSocks5() as socks:
        use_proxy(store, socks.port)
        async with bot_service(store, config, telegram):
            await eventually(lambda: "getUpdates" in telegram.calls)
            store.update({"company": {"name": "Другое"}})
            await asyncio.sleep(0.2)

    assert telegram.calls.count("deleteWebhook") == 1


async def test_recovers_after_unavailable_proxy_is_replaced(store, config, caplog):
    async with FakeSocks5() as dead:
        dead_port = dead.port
    async with FakeTelegram() as telegram, FakeSocks5() as alive:
        use_proxy(store, dead_port)
        async with bot_service(store, config, telegram):
            await eventually(lambda: "Нет связи с Telegram" in caplog.text)
            assert telegram.calls == []

            use_proxy(store, alive.port)
            telegram.send_start(1, STRANGER_ID)
            await eventually(lambda: telegram.sent)


async def test_invalid_env_proxy_waits_for_settings(store, monkeypatch, config, caplog):
    monkeypatch.setenv("TELEGRAM_PROXY_URL", "ftp://nope")
    config = Config()
    async with FakeTelegram() as telegram, FakeSocks5() as socks:
        async with bot_service(store, config, telegram):
            await eventually(lambda: "TELEGRAM_PROXY_URL задан неверно" in caplog.text)
            assert telegram.calls == []

            use_proxy(store, socks.port)
            await eventually(lambda: "getUpdates" in telegram.calls)


async def test_admin_is_told_about_broken_settings(store, config):
    async with FakeTelegram() as telegram, FakeSocks5() as socks:
        use_proxy(store, socks.port)
        async with bot_service(store, config, telegram):
            await eventually(lambda: "getUpdates" in telegram.calls)
            store.path.write_text("{ сломано")
            await eventually(lambda: telegram.sent)
            await asyncio.sleep(0.1)

    [(chat_id, text)] = telegram.sent
    assert chat_id == ADMIN_ID
    assert "settings.json" in text
    # прокси из последней рабочей версии сохранён
    assert telegram.calls.count("deleteWebhook") == 1


async def test_without_token_bot_waits(store, caplog):
    config = Config()
    async with FakeTelegram() as telegram:
        async with bot_service(store, config, telegram) as service:
            await asyncio.sleep(0.05)
            assert not service.done()

    assert "BOT_TOKEN не задан" in caplog.text
    assert telegram.calls == []


async def test_worker_uses_factory_and_follows_proxy_change(store, config, caplog):
    caplog.set_level(logging.INFO)
    async with FakeTelegram() as telegram, FakeSocks5() as first, FakeSocks5() as second:
        use_proxy(store, first.port)
        client = TelegramClient(store, config, telegram.api())
        async with running(
            lambda stop: run_telegram_check(stop, store, config, client, FAST_RETRIES), store
        ):
            await eventually(lambda: telegram.calls.count("getMe") == 1)
            use_proxy(store, second.port)
            await eventually(lambda: telegram.calls.count("getMe") == 2)

    assert first.targets == second.targets == [PROXIED_HOST]
    assert "getUpdates" not in telegram.calls


async def test_bot_writes_status(store, config):
    path = status_path(config.settings_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with FakeTelegram() as telegram, FakeSocks5() as socks:
        use_proxy(store, socks.port)
        async with bot_service(store, config, telegram):
            await eventually(lambda: read_status(path).get("username") == "test_bot")

    status = read_status(path)
    assert status["state"] == "connected"
    assert f"127.0.0.1:{socks.port}" in status["proxy"]


async def test_menu_button_follows_settings(store, config):
    async with FakeTelegram() as telegram, FakeSocks5() as socks:
        use_proxy(store, socks.port)
        client = TelegramClient(store, config, telegram.api())
        runner = BotRunner(
            store,
            config,
            client,
            build_dispatcher(store),
            FAST_RETRIES,
            polling_timeout=0,
            menu_interval=0.02,
        )
        async with running(runner.run, store):
            await eventually(lambda: telegram.menu_urls == [None])
            store.update({"telegram": {"mini_app_url": "https://cal.example/"}})
            await eventually(lambda: telegram.menu_urls[-1] == "https://cal.example/")

    assert "setMyCommands" in telegram.calls
    assert len(telegram.menu_urls) == 2


async def test_worker_sends_notifications(store, config, db):
    from datetime import date

    from app.services.notify.queue import enqueue
    from app.worker import run_notifications

    user = await make_user(db, STRANGER_ID, Role.ACCOUNTANT)
    db.add(
        Task(
            owner_id=user.id,
            source="custom",
            kind="other",
            title="Личное дело",
            due_date=date(2020, 1, 1),
            original_due_date=date(2020, 1, 1),
        )
    )
    await db.commit()
    async with FakeTelegram() as telegram:
        client = TelegramClient(store, config, telegram.api("127.0.0.1"))
        async with running(
            lambda stop: run_notifications(stop, store, config, client, 0.02, 0.02), store
        ):
            from app.services.tasks import today

            await enqueue(db, user.id, "digest", today())
            await db.commit()
            await eventually(lambda: telegram.sent)
        await client.close()

    assert "Личное дело" in telegram.sent[0][1]
