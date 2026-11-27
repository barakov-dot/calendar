"""Вход на сайт виджетом Telegram."""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

import pytest

from app.core.settings_store import get_store
from app.models import Role
from tests.factories import make_user
from tests.fakes import TOKEN

pytestmark = pytest.mark.usefixtures("secrets")


def signed(telegram_id: int, issued: datetime | None = None, token: str = TOKEN) -> dict:
    data = {
        "id": telegram_id,
        "first_name": "Тест",
        "auth_date": int((issued or datetime.now(UTC)).timestamp()),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret = hashlib.sha256(token.encode()).digest()
    return data | {"hash": hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()}


@pytest.fixture
def enabled():
    get_store().update({"telegram": {"login_widget": True, "bot_username": "some_bot"}})


async def login(client, data):
    return await client.post("/api/auth/telegram-widget", json=data)


async def test_options_follow_setting(client):
    get_store().update({"telegram": {"bot_username": "some_bot"}})
    assert (await client.get("/api/auth/options")).json() == {"widget_bot": None}
    get_store().update({"telegram": {"login_widget": True}})
    assert (await client.get("/api/auth/options")).json() == {"widget_bot": "some_bot"}


async def test_disabled_by_default(client, db):
    await make_user(db, 42, Role.ADMIN)

    assert (await login(client, signed(42))).status_code == 404


async def test_invited_user_signs_in(client, db, enabled):
    await make_user(db, 42, Role.ADMIN)

    response = await login(client, signed(42))

    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    me = await client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["role"] == "admin"


@pytest.mark.parametrize(
    ("data", "status"),
    [
        (lambda: signed(42, token="1:другой"), 401),
        (lambda: signed(42) | {"id": 43}, 401),
        (lambda: signed(42, datetime.now(UTC) - timedelta(hours=1)), 401),
        (lambda: signed(99), 403),
    ],
)
async def test_rejected(client, db, enabled, data, status):
    await make_user(db, 42, Role.ADMIN)

    assert (await login(client, data())).status_code == status
