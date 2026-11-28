"""Вход на сайт по коду от бота."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.api import auth as api
from app.models import LoginCode, Role
from app.services import login_code
from tests.factories import auth, make_user

pytestmark = pytest.mark.usefixtures("secrets")


@pytest.fixture
def sent(monkeypatch):
    messages = []

    async def fake(chat_id, text, keyboard=None):
        messages.append((chat_id, text, keyboard))

    monkeypatch.setattr(api, "send_text", fake)
    return messages


@pytest.fixture
async def user(db):
    return await make_user(db, 2, username="Anna_Ivanova", login="ivanova")


async def ask(client, name):
    return await client.post("/api/auth/code-request", json={"login": name})


async def enter(client, request_id, code):
    return await client.post("/api/auth/code-verify", json={"request_id": request_id, "code": code})


def code_of(sent) -> str:
    return re.search(r"\d{6}", sent[-1][1])[0]


@pytest.mark.parametrize("name", ["ivanova", " IVANOVA ", "@anna_ivanova", "Anna_Ivanova"])
async def test_signs_in_by_login_or_username(client, db, user, sent, name):
    asked = await ask(client, name)

    assert asked.status_code == 200, asked.json()
    chat_id, _, keyboard = sent[0]
    assert chat_id == user.telegram_id
    assert keyboard.inline_keyboard[0][0].text == "Это не я"
    response = await enter(client, asked.json()["request_id"], code_of(sent))
    me = await client.get(
        "/api/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"}
    )
    assert me.json()["id"] == user.id
    # сам код в базе не хранится
    row = await db.scalar(select(LoginCode))
    assert code_of(sent) not in row.code_hash


async def test_code_works_only_once(client, user, sent):
    request_id = (await ask(client, "ivanova")).json()["request_id"]

    first = await enter(client, request_id, code_of(sent))
    again = await enter(client, request_id, code_of(sent))

    assert (first.status_code, again.status_code) == (200, 422)


async def test_attempts_are_limited(client, user, sent):
    request_id = (await ask(client, "ivanova")).json()["request_id"]
    right = code_of(sent)
    wrong = "000000" if right != "000000" else "000001"

    for _ in range(login_code.MAX_ATTEMPTS):
        assert (await enter(client, request_id, wrong)).status_code == 422

    assert (await enter(client, request_id, right)).status_code == 422


async def test_expired_and_denied_codes_do_not_work(client, db, user, sent):
    request_id = (await ask(client, "ivanova")).json()["request_id"]
    row = await db.scalar(select(LoginCode))
    assert await login_code.deny(db, row.id, user.id + 1) is False
    assert await login_code.deny(db, row.id, user.id) is True
    assert (await enter(client, request_id, code_of(sent))).status_code == 422

    await db.execute(update(LoginCode).values(created_at=datetime.now(UTC) - timedelta(minutes=2)))
    await db.commit()
    request_id = (await ask(client, "ivanova")).json()["request_id"]
    await db.execute(update(LoginCode).values(expires_at=datetime.now(UTC)))
    await db.commit()
    assert (await enter(client, request_id, code_of(sent))).status_code == 422


@pytest.mark.parametrize(
    "fields",
    [
        {"is_active": False},
        {"pd_consent_at": None},
        {"bot_blocked": True},
    ],
)
async def test_unavailable_user_looks_like_unknown(client, db, sent, fields):
    await make_user(db, 2, login="ivanova", **fields)

    known = await ask(client, "ivanova")
    unknown = await ask(client, "nobody")

    assert sent == []
    assert known.status_code == unknown.status_code == 200
    assert known.json().keys() == unknown.json().keys()


async def test_shared_username_is_ambiguous(client, db, sent):
    await make_user(db, 2, username="same")
    await make_user(db, 3, username="same")

    await ask(client, "same")

    assert sent == []


@pytest.mark.parametrize("name", ["ivanova", "nobody"])
async def test_requests_are_limited_the_same_way(client, db, user, sent, name):
    assert (await ask(client, name)).status_code == 200
    assert (await ask(client, name)).status_code == 429

    for _ in range(login_code.PER_HOUR - 1):
        await db.execute(
            update(LoginCode).values(created_at=datetime.now(UTC) - timedelta(minutes=2))
        )
        await db.commit()
        assert (await ask(client, name)).status_code == 200
    await db.execute(update(LoginCode).values(created_at=datetime.now(UTC) - timedelta(minutes=2)))
    await db.commit()
    assert "через час" in (await ask(client, name)).json()["detail"]


async def test_new_code_cancels_the_previous_one(client, db, user, sent):
    first = (await ask(client, "ivanova")).json()["request_id"]
    old = code_of(sent)
    await db.execute(update(LoginCode).values(created_at=datetime.now(UTC) - timedelta(minutes=2)))
    await db.commit()
    await ask(client, "ivanova")

    assert (await enter(client, first, old)).status_code == 422


@pytest.mark.parametrize(
    ("value", "status"),
    [
        ("Buh.Petrova", 200),
        ("", 200),
        ("ab", 422),
        ("с пробелом", 422),
        ("ivanova", 422),
        ("anna_ivanova", 422),
    ],
)
async def test_admin_sets_login(client, db, user, value, status):
    admin = await make_user(db, 1, Role.ADMIN)
    other = await make_user(db, 3)

    response = await client.patch(
        f"/api/admin/users/{other.id}", json={"login": value}, headers=auth(admin)
    )

    assert response.status_code == status, response.json()
    if status == 200:
        assert response.json()["login"] == (value.lower() or None)
