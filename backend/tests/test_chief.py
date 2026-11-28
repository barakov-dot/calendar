"""Главный бухгалтер: все компании и люди, но без настроек сервиса и без власти над админом."""

import pytest

from app.core.settings_store import get_store
from app.models import InviteKind, Role
from app.services import invites
from tests.factories import auth, make_company, make_user
from tests.test_payments import make_task

pytestmark = pytest.mark.usefixtures("secrets")


@pytest.fixture
async def world(db):
    get_store().update({"telegram": {"bot_username": "some_bot"}})
    admin = await make_user(db, 1, Role.ADMIN)
    chief = await make_user(db, 2, Role.CHIEF)
    other_chief = await make_user(db, 3, Role.CHIEF)
    accountant = await make_user(db, 4)
    helper = await make_user(db, 5, Role.ASSISTANT)
    company = await make_company(db, accountant, 1)
    task = await make_task(db, company)
    private = await make_task(db, company, company_id=None, owner_id=accountant.id, kind="other")
    return locals()


async def test_sees_and_changes_every_company(client, world):
    headers = auth(world["chief"])

    companies = await client.get("/api/companies", headers=headers)
    changed = await client.patch(
        f"/api/tasks/{world['task'].id}", json={"status": "paid"}, headers=headers
    )
    private = await client.get(f"/api/tasks/{world['private'].id}", headers=headers)

    assert [item["id"] for item in companies.json()] == [world["company"].id]
    assert changed.status_code == 200
    assert changed.json()["status_changed_by_role"] == "chief"
    # чужие личные дела не видны
    assert private.status_code == 404


async def test_distributes_work_and_invites(client, db, world):
    headers = auth(world["chief"])
    company = world["company"]

    moved = await client.post(
        f"/api/admin/companies/{company.id}/staff",
        json={"accountant_ids": [world["chief"].id]},
        headers=headers,
    )
    team = await client.post("/api/admin/invites", json={"kind": "assistant"}, headers=headers)
    customer = await client.post(f"/api/companies/{company.id}/invites", json={}, headers=headers)
    substitution = await client.post(
        "/api/admin/substitutions",
        json={
            "accountant_id": world["accountant"].id,
            "substitute_id": world["chief"].id,
            "date_from": "2026-01-01",
            "date_to": "2099-01-01",
        },
        headers=headers,
    )

    assert moved.status_code == 200, moved.text
    assert (team.status_code, customer.status_code) == (201, 201)
    assert substitution.status_code == 201, substitution.text


async def test_users_and_broadcasts(client, world):
    headers = auth(world["chief"])

    listed = await client.get("/api/admin/users", headers=headers)
    renamed = await client.patch(
        f"/api/admin/users/{world['accountant'].id}",
        json={"first_name": "Новое"},
        headers=headers,
    )
    preview = await client.post(
        "/api/admin/broadcasts/preview", json={"roles": ["accountant"]}, headers=headers
    )

    assert (listed.status_code, renamed.status_code, preview.status_code) == (200, 200, 200)


@pytest.mark.parametrize(
    ("target", "change"),
    [
        ("admin", {"first_name": "Х"}),
        ("other_chief", {"is_active": False}),
        ("accountant", {"role": "chief"}),
        ("chief", {"is_active": False}),
    ],
)
async def test_cannot_manage_leaders_or_roles(client, world, target, change):
    response = await client.patch(
        f"/api/admin/users/{world[target].id}", json=change, headers=auth(world["chief"])
    )

    assert response.status_code == 422, response.text


async def test_only_admin_appoints_chiefs(client, db, world):
    chief, admin = auth(world["chief"]), auth(world["admin"])
    url = f"/api/admin/users/{world['accountant'].id}"

    refused = await client.post("/api/admin/invites", json={"kind": "chief"}, headers=chief)
    made = await client.post("/api/admin/invites", json={"kind": "chief"}, headers=admin)
    hidden = await client.get("/api/admin/invites", headers=chief)
    revoke = await client.delete(f"/api/admin/invites/{made.json()['id']}", headers=chief)
    toggle = await client.patch(
        f"/api/admin/accountants/{world['other_chief'].id}",
        json={"is_active": False},
        headers=chief,
    )
    promoted = await client.patch(url, json={"role": "chief"}, headers=admin)
    back = await client.patch(url, json={"role": "accountant"}, headers=admin)
    helper = await client.patch(
        f"/api/admin/users/{world['helper'].id}", json={"role": "chief"}, headers=admin
    )

    assert (refused.status_code, made.status_code) == (403, 201)
    assert hidden.json() == []
    assert (revoke.status_code, toggle.status_code) == (403, 403)
    assert (promoted.json()["role"], back.json()["role"]) == ("chief", "accountant")
    assert helper.status_code == 422


async def test_invite_makes_a_chief(db, world):
    invite = await invites.create(db, InviteKind.CHIEF, world["admin"])

    user = await invites.accept(db, invite.token, invites.TelegramProfile(telegram_id=900))

    assert user.role == Role.CHIEF


@pytest.mark.parametrize(
    "path",
    ["/api/admin/settings", "/api/admin/settings/backups", "/api/admin/calendar"],
)
async def test_service_settings_stay_with_admin(client, world, path):
    assert (await client.get(path, headers=auth(world["chief"]))).status_code == 403


@pytest.mark.parametrize("path", ["/api/admin/users", "/api/admin/invites", "/api/staff"])
@pytest.mark.parametrize("name", ["accountant", "helper"])
async def test_others_have_no_manager_pages(client, world, path, name):
    assert (await client.get(path, headers=auth(world[name]))).status_code == 403
