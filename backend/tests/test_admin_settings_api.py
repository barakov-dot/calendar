import json

import pytest
from sqlalchemy import select

from app.api import admin_settings
from app.core.settings_store import MASK, get_store
from app.models import AuditLog, Role
from app.services.telegram.check import CheckResult
from tests.factories import auth, make_user

pytestmark = pytest.mark.usefixtures("secrets")

SECRET = "very-secret-value"
URL = "/api/admin/settings"
SAVED_PROXY = {"enabled": True, "host": "proxy.example", "port": 1080, "username": "u"}


@pytest.fixture
async def admin(db):
    return auth(await make_user(db, 1, Role.ADMIN))


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("GET", URL),
        ("PATCH", URL),
        ("POST", f"{URL}/test-proxy"),
        ("POST", f"{URL}/test-dadata"),
        ("GET", f"{URL}/backups"),
        ("POST", f"{URL}/backups/x/restore"),
        ("GET", "/api/admin/bot-status"),
    ],
)
async def test_only_admin(client, db, method, url):
    assert (await client.request(method, url, json={})).status_code == 401
    accountant = await make_user(db, 2)
    response = await client.request(method, url, json={}, headers=auth(accountant))
    assert response.status_code == 403


async def test_secrets_are_masked_kept_and_cleared(client, db, admin):
    patch = {"settings": {"dadata": {"api_key": SECRET}}}
    response = await client.patch(URL, json=patch, headers=admin)

    assert response.status_code == 200
    assert SECRET not in response.text
    read = await client.get(URL, headers=admin)
    assert SECRET not in read.text
    assert read.json()["settings"]["dadata"]["api_key"] == MASK
    assert read.json()["settings"]["dadata"]["has_api_key"] is True

    # сохранение формы с маской или пустым полем не меняет секрет
    body = read.json()["settings"]
    body["dadata"]["secret_key"] = ""
    await client.patch(URL, json={"settings": body}, headers=admin)
    assert get_store().get().dadata.api_key == SECRET

    await client.patch(URL, json={"clear": ["dadata.api_key"]}, headers=admin)
    assert get_store().get().dadata.api_key == ""

    entries = (await db.scalars(select(AuditLog).order_by(AuditLog.id))).all()
    assert [entry.payload["fields"] for entry in entries] == [["dadata.api_key"]] * 2
    assert SECRET not in json.dumps([entry.payload for entry in entries])


async def test_invalid_value_is_rejected_without_leaking(client, db, admin):
    patch = {"settings": {"dadata": {"api_key": [SECRET]}}}

    response = await client.patch(URL, json=patch, headers=admin)

    assert response.status_code == 422
    assert "dadata.api_key" in response.json()["detail"]
    assert SECRET not in response.text
    assert (await db.scalars(select(AuditLog))).all() == []


async def test_broken_file_is_reported(client, admin):
    store = get_store()
    store.ensure_file()
    store.path.write_text("{")

    response = await client.get(URL, headers=admin)

    assert "JSON" in response.json()["file_error"]


async def test_backups_and_restore(client, db, admin):
    get_store().ensure_file()
    await client.patch(URL, json={"settings": {"company": {"name": "Новое"}}}, headers=admin)
    [backup] = (await client.get(f"{URL}/backups", headers=admin)).json()
    assert backup["valid"] and backup["created_at"]

    response = await client.post(f"{URL}/backups/{backup['name']}/restore", headers=admin)

    assert response.json()["settings"]["company"]["name"] != "Новое"
    assert len((await client.get(f"{URL}/backups", headers=admin)).json()) == 2
    last = (await db.scalars(select(AuditLog).order_by(AuditLog.id.desc()))).first()
    assert (last.action, last.payload["fields"]) == ("settings.restore", ["company.name"])


@pytest.mark.parametrize("name", ["settings-0.json", "..%2Fsettings.json", "settings.json"])
async def test_restore_unknown_backup(client, admin, name):
    get_store().ensure_file()

    response = await client.post(f"{URL}/backups/{name}/restore", headers=admin)

    assert response.status_code == 404


async def test_restore_broken_backup(client, admin):
    store = get_store()
    store.ensure_file()
    store.backups_dir.mkdir()
    (store.backups_dir / "settings-20260101-000000-000000.json").write_text("{")

    response = await client.post(
        f"{URL}/backups/settings-20260101-000000-000000.json/restore", headers=admin
    )

    assert response.status_code == 422


@pytest.fixture
def checked(monkeypatch):
    calls = []

    async def fake(config, proxy):
        calls.append(proxy)
        return CheckResult(True, "Бот @x доступен, задержка 1 мс", 1)

    monkeypatch.setattr(admin_settings, "check_connection", fake)
    return calls


async def test_proxy_check_uses_saved_password_without_saving(client, admin, checked):
    get_store().update({"telegram": {"proxy": SAVED_PROXY | {"password": SECRET}}})
    before = get_store().path.read_bytes()

    response = await client.post(
        f"{URL}/test-proxy", json=SAVED_PROXY | {"password": ""}, headers=admin
    )

    assert response.json()["ok"] is True
    assert SECRET not in response.text
    assert SECRET in checked[0].url
    assert get_store().path.read_bytes() == before


@pytest.mark.parametrize("change", [{"host": "evil.example"}, {"port": 9}, {"username": "x"}])
async def test_saved_password_is_not_sent_elsewhere(client, admin, checked, change):
    get_store().update({"telegram": {"proxy": SAVED_PROXY | {"password": SECRET}}})

    await client.post(f"{URL}/test-proxy", json=SAVED_PROXY | change, headers=admin)

    assert SECRET not in checked[0].url


async def test_proxy_check_validates_input(client, admin, checked):
    response = await client.post(f"{URL}/test-proxy", json={"enabled": True}, headers=admin)

    assert response.status_code == 422
    assert checked == []


async def test_dadata_check_uses_saved_keys(client, admin, monkeypatch):
    get_store().update({"dadata": {"api_key": SECRET}})
    calls = []

    async def fake(api_key, secret_key, timeout_seconds):
        calls.append((api_key, secret_key))
        return "работает"

    monkeypatch.setattr(admin_settings, "check_keys", fake)

    response = await client.post(
        f"{URL}/test-dadata", json={"api_key": MASK, "secret_key": "new"}, headers=admin
    )

    assert response.json() == {"ok": True, "message": "работает"}
    assert calls == [(SECRET, "new")]


async def test_bot_status_unknown(client, admin):
    response = await client.get("/api/admin/bot-status", headers=admin)

    assert response.json() == {"state": "unknown", "link": None}
