"""«Клиент платит сам»: отметка оплаты и её отмена (PLAN.md, разделы 4.3 и 8)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.settings_store import get_store
from app.models import AuditLog, Notification, Role, Task
from tests.factories import auth, link_client, make_company, make_user

pytestmark = pytest.mark.usefixtures("secrets")


async def make_task(db, company, **fields) -> Task:
    values = {
        "company_id": company.id,
        "source": "custom",
        "kind": "payment",
        "title": "Платёж",
        "due_date": datetime.now(UTC).date(),
        "original_due_date": datetime.now(UTC).date(),
        "client_visible": True,
    } | fields
    task = Task(**values)
    db.add(task)
    await db.commit()
    return task


@pytest.fixture
async def world(db):
    admin = await make_user(db, 1, Role.ADMIN)
    helper = await make_user(db, 7, Role.ASSISTANT)
    accountant = await make_user(db, 2)
    other_accountant = await make_user(db, 3)
    payer = await make_user(db, 10, Role.CLIENT, first_name="Пётр")
    viewer = await make_user(db, 11, Role.CLIENT)
    outsider = await make_user(db, 12, Role.CLIENT)
    company = await make_company(db, accountant, 1)
    other = await make_company(db, other_accountant, 2)
    await link_client(db, company, payer, can_mark_paid=True)
    await link_client(db, company, viewer)
    await link_client(db, other, outsider, can_mark_paid=True)
    task = await make_task(db, company)
    return locals()


async def post(client, user, task, action="mark-paid"):
    return await client.post(f"/api/tasks/{task.id}/{action}", headers=auth(user))


async def fresh(db, task) -> Task:
    return await db.get(Task, task.id, populate_existing=True)


async def test_payer_marks_and_accountant_is_notified(client, db, world):
    task = world["task"]

    response = await post(client, world["payer"], task)

    body = response.json()
    assert response.status_code == 200, body
    assert (body["status"], body["can_mark_paid"], body["can_unmark_paid"]) == (
        "paid",
        False,
        True,
    )
    assert "comment" not in body
    task = await fresh(db, task)
    assert (task.status_changed_by, task.status_changed_by_role) == (world["payer"].id, "client")
    [note] = (await db.scalars(select(Notification))).all()
    assert (note.user_id, note.type, note.task_id) == (
        world["accountant"].id,
        "client_marked_paid",
        task.id,
    )
    [entry] = (await db.scalars(select(AuditLog))).all()
    assert entry.action == "task.mark_paid"
    assert (await post(client, world["payer"], task)).status_code == 409


async def test_without_accountant_admins_are_notified(client, db, world):
    world["accountant"].is_active = False
    await db.commit()

    await post(client, world["payer"], world["task"])

    [note] = (await db.scalars(select(Notification))).all()
    assert note.user_id == world["admin"].id


@pytest.mark.parametrize(
    ("who", "code"),
    [
        ("viewer", 403),  # флаг соседа по компании не даёт прав
        ("outsider", 404),  # свой флаг не открывает чужую компанию
        ("accountant", 403),
        ("admin", 403),
        ("helper", 403),
    ],
)
async def test_who_cannot_mark(client, db, world, who, code):
    response = await post(client, world[who], world["task"])

    assert response.status_code == code
    assert (await fresh(db, world["task"])).status == "planned"
    assert (await db.scalars(select(Notification))).all() == []


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"kind": "report"}, 403),
        ({"kind": "other"}, 403),
        ({"client_visible": False}, 404),
        ({"status": "not_required"}, 409),
    ],
)
async def test_what_cannot_be_marked(client, db, world, fields, code):
    task = await make_task(db, world["company"], **fields)

    response = await post(client, world["payer"], task)

    assert response.status_code == code
    assert (await fresh(db, task)).status == fields.get("status", "planned")


async def test_client_cannot_change_amount(client, db, world):
    response = await client.patch(
        f"/api/tasks/{world['task'].id}",
        json={"amount_kopecks": 1},
        headers=auth(world["payer"]),
    )

    assert response.status_code == 403


async def test_unmark_own_within_hours(client, db, world):
    task, payer = world["task"], world["payer"]
    await post(client, payer, task)

    response = await post(client, payer, task, "unmark-paid")

    assert response.json()["status"] == "planned"
    assert response.json()["can_mark_paid"] is True
    # повторная отметка снова сообщает бухгалтеру, без дублей
    await post(client, payer, task)
    assert len((await db.scalars(select(Notification))).all()) == 1


async def test_unmark_after_deadline(client, db, world):
    task, payer = world["task"], world["payer"]
    await post(client, payer, task)
    row = await fresh(db, task)
    row.status_changed_at = datetime.now(UTC) - timedelta(hours=25)
    await db.commit()

    assert (await post(client, payer, task, "unmark-paid")).status_code == 403
    get_store().update({"tasks": {"client_can_unmark_own_paid_hours": 48}})
    assert (await post(client, payer, task, "unmark-paid")).status_code == 200


async def test_client_cannot_unmark_foreign_mark(client, db, world):
    task = await make_task(
        db,
        world["company"],
        status="paid",
        status_changed_by=world["accountant"].id,
        status_changed_by_role="accountant",
        status_changed_at=datetime.now(UTC),
    )

    assert (await post(client, world["payer"], task, "unmark-paid")).status_code == 403
    # а сотрудник этой кнопкой не снимает собственную отметку бухгалтера
    assert (await post(client, world["accountant"], task, "unmark-paid")).status_code == 409
    assert (await fresh(db, task)).status == "paid"


async def test_flag_removed_removes_rights(client, db, world):
    task, payer = world["task"], world["payer"]
    await post(client, payer, task)
    await client.patch(
        f"/api/companies/{world['company'].id}/members/{payer.id}",
        json={"can_mark_paid": False},
        headers=auth(world["accountant"]),
    )

    assert (await post(client, payer, task, "unmark-paid")).status_code == 403


@pytest.mark.parametrize(
    ("who", "code"),
    [("accountant", 200), ("admin", 200), ("other_accountant", 404), ("helper", 403)],
)
async def test_staff_cancels_client_mark(client, db, world, who, code):
    await post(client, world["payer"], world["task"])

    response = await post(client, world[who], world["task"], "unmark-paid")

    assert response.status_code == code
    expected = "planned" if code == 200 else "paid"
    assert (await fresh(db, world["task"])).status == expected


async def test_notification_preferences_are_personal(client, world):
    headers = auth(world["payer"])
    url = "/api/me/notification-settings"

    saved = await client.put(url, json={"offsets_days": [1, 5, 5]}, headers=headers)

    assert saved.json()["offsets_days"] == [5, 1]
    assert saved.json()["defaults"]["offsets_days"] == [7, 3, 1]
    other = await client.get(url, headers=auth(world["viewer"]))
    assert other.json()["offsets_days"] is None
    for bad in ({"offsets_days": [0]}, {"digest_time": "25:00"}, {"user_id": 1}):
        assert (await client.put(url, json=bad, headers=headers)).status_code == 422
    assert (await client.get(url)).status_code == 401


async def test_contacts(client, world):
    get_store().update({"company": {"support_contact": "@help"}})

    body = (await client.get("/api/me/contacts", headers=auth(world["payer"]))).json()

    assert body["support_contact"] == "@help"
    assert [item["company"] for item in body["accountants"]] == ["ООО «Компания 1»"]
