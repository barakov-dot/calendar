import pytest
from sqlalchemy import select

from app.core.settings_store import get_store
from app.models import AuditLog, Role
from app.services import invites
from tests.factories import auth, make_user

pytestmark = pytest.mark.usefixtures("secrets")


@pytest.fixture
async def admin(db):
    get_store().update({"telegram": {"bot_username": "some_bot"}})
    return await make_user(db, 1, Role.ADMIN)


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("GET", "/api/admin/accountants", None),
        ("PATCH", "/api/admin/accountants/1", {"is_active": False}),
        ("GET", "/api/admin/invites", None),
        ("POST", "/api/admin/invites", {"kind": "accountant"}),
        ("DELETE", "/api/admin/invites/1", None),
    ],
)
async def test_only_admin(client, db, method, url, body):
    assert (await client.request(method, url, json=body)).status_code == 401
    for telegram_id, role in ((2, Role.ACCOUNTANT), (3, Role.CLIENT)):
        user = await make_user(db, telegram_id, role)
        response = await client.request(method, url, json=body, headers=auth(user))
        assert response.status_code == 403


async def test_invite_lifecycle(client, db, admin):
    headers = auth(admin)

    created = await client.post("/api/admin/invites", json={}, headers=headers)
    assert created.status_code == 201
    invite = created.json()
    assert invite["link"].startswith("https://t.me/some_bot?start=inv_")
    assert len(invite["link"].split("start=")[1]) <= 64  # ограничение Telegram
    listed = (await client.get("/api/admin/invites", headers=headers)).json()
    assert [item["id"] for item in listed] == [invite["id"]]

    url = f"/api/admin/invites/{invite['id']}"
    assert (await client.delete(url, headers=headers)).status_code == 204
    assert (await client.delete(url, headers=headers)).status_code == 404
    assert (await client.get("/api/admin/invites", headers=headers)).json() == []
    actions = (await db.scalars(select(AuditLog.action).order_by(AuditLog.id))).all()
    assert actions == ["invite.create", "invite.revoke"]


async def test_client_invite_needs_company(client, admin):
    response = await client.post("/api/admin/invites", json={"kind": "client"}, headers=auth(admin))

    assert response.status_code == 422


async def test_deactivate_accountant(client, db, admin):
    accountant = await make_user(db, 2)
    client_user = await make_user(db, 3, Role.CLIENT)
    headers = auth(admin)

    listed = (await client.get("/api/admin/accountants", headers=headers)).json()
    assert [item["id"] for item in listed] == [accountant.id]

    url = f"/api/admin/accountants/{accountant.id}"
    response = await client.patch(url, json={"is_active": False}, headers=headers)
    assert response.json()["is_active"] is False
    assert (await client.get("/api/me", headers=auth(accountant))).status_code == 401

    for user in (admin, client_user):
        response = await client.patch(
            f"/api/admin/accountants/{user.id}", json={"is_active": False}, headers=headers
        )
        assert response.status_code == 404


async def test_invite_and_manage_assistant(client, db, admin):
    headers = auth(admin)
    invite = await client.post("/api/admin/invites", json={"kind": "assistant"}, headers=headers)
    assert invite.json()["kind"] == "assistant"
    token = invite.json()["link"].split("start=inv_")[1]

    user = await invites.accept(db, token, invites.TelegramProfile(50, "Помощник"))

    assert user.role == "assistant"
    team = (await client.get("/api/admin/accountants", headers=headers)).json()
    assert [(item["id"], item["role"]) for item in team] == [(user.id, "assistant")]
    url = f"/api/admin/accountants/{user.id}"
    response = await client.patch(url, json={"is_active": False}, headers=headers)
    assert response.json()["is_active"] is False
    # помощник не управляет командой и настройками
    await client.patch(url, json={"is_active": True}, headers=headers)
    for path in ("/api/admin/accountants", "/api/admin/invites", "/api/admin/settings"):
        assert (await client.get(path, headers=auth(user))).status_code == 403
