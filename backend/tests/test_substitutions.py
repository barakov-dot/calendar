"""Замещение бухгалтера: права на эти дни и перенаправление уведомлений."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.permissions import business_today, get_accessible_company_ids
from app.core.settings_store import get_store
from app.models import Notification, Role, Substitution, Task
from app.services.notify.planner import plan
from app.services.notify.sender import digest_tasks
from app.services.payments import responsible
from tests.factories import auth, link_client, make_company, make_user
from tests.test_notifications import NOW, TODAY, add_task

pytestmark = pytest.mark.usefixtures("secrets")


@pytest.fixture
async def world(db):
    admin = await make_user(db, 1, Role.ADMIN)
    helper = await make_user(db, 6, Role.ASSISTANT)
    away = await make_user(db, 2, first_name="Анна")
    stand_in = await make_user(db, 3, first_name="Вера", username="vera")
    other = await make_user(db, 4)
    client_user = await make_user(db, 10, Role.CLIENT)
    company = await make_company(db, away, 1)
    own = await make_company(db, stand_in, 2)
    await link_client(db, company, client_user, can_mark_paid=True)
    return locals()


async def substitute(db, world, start=0, end=0, today=None) -> Substitution:
    today = today or business_today()
    row = Substitution(
        accountant_id=world["away"].id,
        substitute_id=world["stand_in"].id,
        date_from=today + timedelta(days=start),
        date_to=today + timedelta(days=end),
        created_by=world["admin"].id,
    )
    db.add(row)
    await db.commit()
    return row


@pytest.mark.parametrize(
    ("start", "end", "granted"), [(0, 0, True), (-5, -1, False), (1, 5, False)]
)
async def test_access_only_during_the_period(client, db, world, start, end, granted):
    await substitute(db, world, start, end)
    company, own = world["company"], world["own"]

    ids = await get_accessible_company_ids(db, world["stand_in"])
    response = await client.patch(
        f"/api/companies/{company.id}",
        json={"company": {"notes": "заметка"}},
        headers=auth(world["stand_in"]),
    )

    assert ids == ({company.id, own.id} if granted else {own.id})
    assert response.status_code == (200 if granted else 404)
    # замещение работает в одну сторону
    assert await get_accessible_company_ids(db, world["away"]) == {company.id}
    assert await get_accessible_company_ids(db, world["other"]) == set()


async def test_substitute_changes_tasks(client, db, world):
    await substitute(db, world)
    task = await add_task(db, world["company"], business_today())

    response = await client.patch(
        f"/api/tasks/{task.id}", json={"status": "paid"}, headers=auth(world["stand_in"])
    )

    assert response.status_code == 200, response.text


async def test_notifications_go_to_substitute(db, world):
    await substitute(db, world, today=TODAY)
    task = await add_task(db, world["company"], TODAY - timedelta(days=1))
    empty = await add_task(
        db, world["company"], TODAY + timedelta(days=1), amount_kopecks=None, needs_amount=True
    )

    await plan(db, get_store().get(), NOW)

    rows = list(await db.scalars(select(Notification)))
    staff = {(r.user_id, r.type, r.task_id) for r in rows if r.type in ("overdue", "fill_amount")}
    stand_in = world["stand_in"].id
    assert {(stand_in, "overdue", task.id), (stand_in, "fill_amount", empty.id)} <= staff
    assert world["away"].id not in {user for user, _, _ in staff if user != 10}
    seen = {t.id for t, _ in await digest_tasks(db, world["stand_in"], TODAY)}
    assert seen == {task.id, empty.id}
    assert await digest_tasks(db, world["away"], TODAY) == []


async def test_unreachable_substitute_does_not_take_messages(db, world):
    await substitute(db, world, today=TODAY)
    world["stand_in"].bot_blocked = True
    task = await add_task(db, world["company"], TODAY - timedelta(days=1))

    await plan(db, get_store().get(), NOW)

    overdue = await db.scalars(select(Notification.user_id).where(Notification.type == "overdue"))
    assert world["away"].id in set(overdue)
    assert [t.id for t, _ in await digest_tasks(db, world["away"], TODAY)] == [task.id]


async def test_client_mark_and_contacts(client, db, world):
    await substitute(db, world)
    assert [u.id for u in await responsible(db, world["company"].id)] == [world["stand_in"].id]

    response = await client.get("/api/me/contacts", headers=auth(world["client_user"]))

    [contact] = response.json()["accountants"]
    assert (contact["username"], contact["substitute"]) == ("vera", True)


def body(world, **fields) -> dict:
    today = business_today()
    return {
        "accountant_id": world["away"].id,
        "substitute_id": world["stand_in"].id,
        "date_from": str(today),
        "date_to": str(today + timedelta(days=14)),
    } | fields


async def test_admin_manages_substitutions(client, db, world):
    headers = auth(world["admin"])
    url = "/api/admin/substitutions"

    created = await client.post(url, json=body(world), headers=headers)

    assert created.status_code == 201, created.text
    [row] = created.json()
    assert (row["accountant_name"], row["active"]) == ("Анна", True)
    assert (await client.post(url, json=body(world), headers=headers)).status_code == 422
    for name in ("away", "stand_in"):
        mine = await client.get("/api/me/substitutions", headers=auth(world[name]))
        assert [item["id"] for item in mine.json()] == [row["id"]]
    assert (await client.get("/api/me/substitutions", headers=auth(world["other"]))).json() == []
    assert (await client.delete(f"{url}/{row['id']}", headers=headers)).status_code == 204
    assert await db.scalar(select(Substitution)) is None


@pytest.mark.parametrize(
    "change",
    [
        {"substitute_id": "away"},
        {"substitute_id": "helper"},
        {"substitute_id": "client_user"},
        {"date_to": "2020-01-01", "date_from": "2020-01-01"},
        {"date_from": "2099-01-02", "date_to": "2099-01-01"},
    ],
)
async def test_wrong_substitution_is_rejected(client, world, change):
    change = {k: world[v].id if v in world else v for k, v in change.items()}

    response = await client.post(
        "/api/admin/substitutions", json=body(world, **change), headers=auth(world["admin"])
    )

    assert response.status_code == 422


@pytest.mark.parametrize("name", ["away", "helper", "client_user"])
async def test_only_admin(client, db, world, name):
    row = await substitute(db, world)
    headers = auth(world[name])
    url = "/api/admin/substitutions"

    assert (await client.get(url, headers=headers)).status_code == 403
    assert (await client.post(url, json=body(world), headers=headers)).status_code == 403
    assert (await client.delete(f"{url}/{row.id}", headers=headers)).status_code == 403
    assert await db.scalar(select(Task)) is None
