import asyncio
import json
import logging
import os
import stat
import threading
from pathlib import Path

import pytest

from app.core import settings_store
from app.core.settings_store import (
    BACKUPS_KEPT,
    MASK,
    AppSettings,
    SettingsError,
    SettingsStore,
    masked_settings,
    parse_settings,
)

SECRET = "very-secret-value"


@pytest.fixture
def store(tmp_path):
    return SettingsStore(tmp_path / "settings.json", check_interval=0)


def write_raw(path: Path, content: str) -> None:
    """Имитирует ручную правку файла."""
    path.write_text(content, encoding="utf-8")
    # гарантируем новый mtime даже при быстрой записи
    mtime = path.stat().st_mtime_ns + 1_000_000
    os.utime(path, ns=(mtime, mtime))


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_example_file_is_valid_and_has_all_fields():
    example = json.loads(Path("/app/config/settings.example.json").read_text(encoding="utf-8"))

    parse_settings(example)

    def keys(data, prefix=""):
        for key, value in data.items():
            yield prefix + key
            if isinstance(value, dict):
                yield from keys(value, f"{prefix}{key}.")

    assert set(keys(example)) == set(keys(AppSettings().model_dump()))


def test_missing_file_gives_defaults_without_creating(store):
    assert store.get() == AppSettings()
    assert not store.path.exists()


def test_ensure_file_creates_defaults_with_mode_600(store):
    store.ensure_file()

    assert parse_settings(json.loads(store.path.read_text())) == AppSettings()
    assert mode(store.path) == 0o600


def test_ensure_file_keeps_existing(store):
    write_raw(store.path, '{"company": {"name": "Своё"}}')

    store.ensure_file()

    assert store.get().company.name == "Своё"
    assert store.path.read_text() == '{"company": {"name": "Своё"}}'


def test_update_writes_backup_of_previous_version(store):
    store.ensure_file()
    before = store.path.read_bytes()

    store.update({"company": {"name": "Новое"}}, user=1)

    assert store.get().company.name == "Новое"
    [backup] = store.list_backups()
    assert backup.read_bytes() == before
    assert mode(backup) == 0o600
    assert mode(store.path) == 0o600


def test_update_without_changes_does_nothing(store):
    store.ensure_file()

    store.update({"company": {"timezone": "Europe/Moscow"}})

    assert store.list_backups() == []


def test_keeps_only_latest_backups(store):
    store.ensure_file()
    for number in range(BACKUPS_KEPT + 5):
        store.update({"company": {"name": f"v{number}"}})

    backups = store.list_backups()
    assert len(backups) == BACKUPS_KEPT
    assert json.loads(backups[0].read_text())["company"]["name"] == f"v{BACKUPS_KEPT + 3}"


def test_failed_write_leaves_old_file_and_no_temporary(store, monkeypatch):
    store.ensure_file()
    before = store.path.read_bytes()
    real_replace = os.replace

    def fail_on_main_file(source, target):
        if Path(target) == store.path:
            raise OSError("диск полон")
        real_replace(source, target)

    monkeypatch.setattr(settings_store.os, "replace", fail_on_main_file)

    with pytest.raises(OSError, match="диск полон"):
        store.update({"company": {"name": "Новое"}})

    assert store.path.read_bytes() == before
    assert list(store.path.parent.glob(".tmp-*")) == []
    assert store.get().company.name == AppSettings().company.name


@pytest.mark.parametrize(
    "patch",
    [
        {"telegram": {"proxy": {"port": 70000}}},
        {"telegram": {"proxy": {"enabled": True}}},
        {"telegram": {"proxy": {"host": "socks5://example.org"}}},
        {"notifications": {"digest_time": "25:00"}},
        {"notifications": {"default_client_offsets_days": [0]}},
        {"company": {"timezone": "Mars/Olympus"}},
        {"unknown": 1},
    ],
)
def test_invalid_update_is_rejected_and_not_written(store, patch):
    store.ensure_file()
    before = store.path.read_bytes()

    with pytest.raises(SettingsError):
        store.update(patch)

    assert store.path.read_bytes() == before


def test_validation_error_does_not_leak_values(store, caplog):
    write_raw(store.path, json.dumps({"telegram": {"proxy": {"password": [SECRET]}}}))

    store.get()

    assert "telegram.proxy.password" in store.last_error
    assert SECRET not in store.last_error
    assert SECRET not in caplog.text


def test_broken_file_keeps_last_valid_and_reports_once(store, caplog):
    store.ensure_file()
    store.update({"company": {"name": "Рабочее"}})
    errors: list[str] = []
    store.subscribe_errors(errors.append)

    write_raw(store.path, "{ это не json")
    assert store.get().company.name == "Рабочее"
    assert store.get().company.name == "Рабочее"
    write_raw(store.path, "{ это не json ")
    store.get()

    assert len(errors) == 1
    assert "синтаксическая ошибка JSON" in errors[0]
    assert caplog.text.count("не применён") == 1


def test_fixed_file_is_applied_again(store):
    store.ensure_file()
    write_raw(store.path, "{")
    store.get()

    write_raw(store.path, '{"company": {"name": "Исправлено"}}')

    assert store.get().company.name == "Исправлено"
    assert store.last_error is None


def test_broken_file_at_start_uses_latest_valid_backup(store):
    store.ensure_file()
    store.update({"company": {"name": "Первое"}})
    store.update({"company": {"name": "Второе"}})
    write_raw(store.path, "{")

    fresh = SettingsStore(store.path)

    assert fresh.get().company.name == "Первое"
    assert fresh.last_error


def test_broken_file_without_backups_uses_defaults(store):
    write_raw(store.path, "[]")

    assert store.get() == AppSettings()


def test_update_over_broken_file_preserves_it_in_backups(store):
    store.ensure_file()
    store.get()
    write_raw(store.path, "{ ручная правка")

    store.update({"company": {"name": "Из веба"}})

    assert store.list_backups()[0].read_text() == "{ ручная правка"
    assert store.get().company.name == "Из веба"


def test_get_returns_copy(store):
    store.get().notifications.default_client_offsets_days.append(99)

    assert store.get().notifications.default_client_offsets_days == [7, 3, 1]


def test_get_checks_file_not_more_often_than_interval(tmp_path):
    now = [0.0]
    store = SettingsStore(tmp_path / "settings.json", check_interval=2, clock=lambda: now[0])
    store.ensure_file()
    write_raw(store.path, '{"company": {"name": "Позже"}}')

    now[0] = 1.0
    assert store.get().company.name != "Позже"
    now[0] = 2.5
    assert store.get().company.name == "Позже"


async def test_watch_notifies_subscribers_about_manual_edit(store):
    store.ensure_file()
    received: asyncio.Queue[AppSettings] = asyncio.Queue()
    store.subscribe(received.put_nowait)
    task = asyncio.create_task(store.watch(interval=0.01))
    await asyncio.sleep(0.03)
    assert received.empty()

    write_raw(store.path, '{"company": {"name": "Руками"}}')
    settings = await asyncio.wait_for(received.get(), timeout=2)
    task.cancel()

    assert settings.company.name == "Руками"


def test_failing_subscriber_does_not_break_others(store):
    store.ensure_file()
    names: list[str] = []

    def broken(_):
        raise RuntimeError

    store.subscribe(broken)
    store.subscribe(lambda settings: names.append(settings.company.name))

    store.update({"company": {"name": "Новое"}})

    assert names == ["Новое"]


def test_masked_settings_hide_secrets():
    settings = parse_settings({"dadata": {"api_key": SECRET}})

    data = masked_settings(settings)

    assert data["dadata"]["api_key"] == MASK
    assert data["dadata"]["has_api_key"] is True
    assert data["dadata"]["secret_key"] == ""
    assert data["telegram"]["proxy"]["has_password"] is False
    assert SECRET not in json.dumps(data)


@pytest.mark.parametrize("value", ["", MASK, None])
def test_empty_secret_means_keep(store, value):
    store.update({"dadata": {"api_key": SECRET}})

    store.update({"dadata": {"api_key": value, "timeout_seconds": 20}})

    assert store.get().dadata.api_key == SECRET
    assert store.get().dadata.timeout_seconds == 20


def test_masked_data_can_be_saved_back(store):
    store.update({"dadata": {"api_key": SECRET}})

    store.update(masked_settings(store.get()))

    assert store.get().dadata.api_key == SECRET


def test_secret_can_be_cleared_explicitly(store):
    store.update({"dadata": {"api_key": SECRET}})

    store.update({}, clear=["dadata.api_key"])

    assert store.get().dadata.api_key == ""
    with pytest.raises(SettingsError):
        store.update({}, clear=["company.name"])


def test_secrets_are_not_logged_on_update(store, caplog):
    caplog.set_level(logging.INFO)

    store.update({"dadata": {"api_key": SECRET}}, user=42)

    assert "dadata.api_key" in caplog.text
    assert SECRET not in caplog.text


def test_parallel_writers_do_not_lose_changes(tmp_path):
    path = tmp_path / "settings.json"
    SettingsStore(path).ensure_file()
    patches = [
        {"company": {"name": "A"}},
        {"company": {"support_contact": "@b"}},
        {"telegram": {"bot_username": "c_bot"}},
        {"dadata": {"timeout_seconds": 30}},
        {"tasks": {"generation_horizon_months_ahead": 12}},
    ]
    threads = [
        threading.Thread(target=SettingsStore(path).update, args=(patch,)) for patch in patches
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    result = SettingsStore(path).get()
    assert (result.company.name, result.company.support_contact) == ("A", "@b")
    assert result.telegram.bot_username == "c_bot"
    assert result.dadata.timeout_seconds == 30
    assert result.tasks.generation_horizon_months_ahead == 12
