"""Несколько бухгалтеров и помощников у компании."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.core.permissions import business_today, get_accessible_company_ids
from app.core.settings_store import get_store
from app.models import (
    CompanyStaff,
    Invite,
    Notification,
    NotificationType,
    Role,
    Substitution,
    Task,
)
from app.services import payments
from app.services.inn import with_check_digits
from app.services.notify import planner, sender
from tests.factories import assign, auth, link_client, make_company, make_user

pytestmark = pytest.mark.usefixtures("secrets")

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=ZoneInfo("Europe/Moscow"))
YESTERDAY = date(2026, 10, 13)


@pytest.fixture
async def world(db):
    get_store().update({"telegram": {"bot_username": "some_bot"}})
    admin = await make_user(db, 1, Role.ADMIN)
    anna = await make_user(db, 2, first_name="Анна")
    boris = await make_user(db, 3, first_name="Борис")
    helper = await make_user(db, 4, Role.ASSISTANT, first_name="Дина")
    spare = await make_user(db, 5, Role.ASSISTANT)
    payer = await make_user(db, 6, Role.CLIENT)
    company = await make_company(db, anna, 1)
    other = await make_company(db, boris, 2)
    await link_client(db, company, payer)
    return locals()


async def set_staff(client, world, accountants, assistants=(), user="admin"):
    return await client.post(
        f"/api/admin/companies/{world['company'].id}/staff",
        json={
            "accountant_ids": [world[name].id for name in accountants],
            "assistant_ids": [world[name].id for name in assistants],
        },
        headers=auth(world[user]),
    )


async def overdue_task(db, company) -> Task:
    task = Task(
        company_id=company.id,
        source="custom",
        kind="payment",
        title="Налог",
        due_date=YESTERDAY,
        original_due_date=YESTERDAY,
    )
    db.add(task)
    await db.commit()
    return task


async def queued(db, kind) -> set[int]:
    rows = await db.scalars(select(Notification.user_id).where(Notification.type == kind))
    return set(rows)


async def test_every_accountant_and_assigned_assistant_have_access(client, db, world):
    response = await set_staff(client, world, ["anna", "boris"], ["helper"])

    body = response.json()
    assert response.status_code == 200, body
    assert [item["name"] for item in body["accountants"]] == ["Анна", "Борис"]
    assert [item["name"] for item in body["assistants"]] == ["Дина"]
    assert body["accountant_name"] == "Анна, Борис"
    company, other = world["company"].id, world["other"].id
    assert await get_accessible_company_ids(db, world["anna"]) == {company}
    assert await get_accessible_company_ids(db, world["boris"]) == {company, other}
    assert await get_accessible_company_ids(db, world["helper"]) == {company}
    assert await get_accessible_company_ids(db, world["spare"]) == set()
    edited = await client.patch(
        f"/api/companies/{company}",
        json={"company": {"notes": "общая"}},
        headers=auth(world["boris"]),
    )
    assert edited.status_code == 200
    listed = await client.get("/api/companies", headers=auth(world["helper"]))
    assert [item["accountant_name"] for item in listed.json()] == ["Анна, Борис"]
    contacts = await client.get("/api/me/contacts", headers=auth(world["payer"]))
    assert [item["accountant"] for item in contacts.json()["accountants"]] == ["Анна", "Борис"]


@pytest.mark.parametrize(
    ("accountants", "assistants"),
    [([], ["helper"]), (["payer"], []), (["helper"], []), (["anna"], ["boris"])],
)
async def test_wrong_staff_is_rejected(client, db, world, accountants, assistants):
    response = await set_staff(client, world, accountants, assistants)

    assert response.status_code == 422
    assert await get_accessible_company_ids(db, world["anna"]) == {world["company"].id}


async def test_disabled_member_does_not_block_changes(client, db, world):
    world["anna"].is_active = False
    await db.commit()

    kept = await set_staff(client, world, ["anna", "boris"])
    dropped = await set_staff(client, world, ["boris"])
    returned = await set_staff(client, world, ["anna", "boris"])

    assert [item["is_active"] for item in kept.json()["accountants"]] == [False, True]
    assert dropped.status_code == 200
    assert returned.status_code == 422


async def test_only_invites_of_removed_staff_are_revoked(client, db, world):
    await set_staff(client, world, ["anna", "boris"])
    for name in ("anna", "admin"):
        db.add(
            Invite(
                token=name,
                kind="client",
                company_id=world["company"].id,
                created_by=world[name].id,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
    await db.commit()

    await set_staff(client, world, ["boris"])

    rows = await db.scalars(select(Invite).execution_options(populate_existing=True))
    assert {item.token: item.revoked_at is not None for item in rows} == {
        "anna": True,
        "admin": False,
    }


async def test_accountant_cannot_change_staff(client, world):
    assert (await set_staff(client, world, ["anna"], user="anna")).status_code == 403


async def test_new_company_takes_chosen_staff(client, db, world):
    company = {"name": "ООО «Новая»", "entity_type": "ooo", "main_regime": "usn6"}
    response = await client.post(
        "/api/companies",
        json={
            "company": company | {"inn": with_check_digits("000000003")},
            "accountant_ids": [world["anna"].id, world["boris"].id],
            "assistant_ids": [world["helper"].id],
        },
        headers=auth(world["admin"]),
    )

    assert response.status_code == 201, response.text
    rows = await db.scalars(
        select(CompanyStaff.user_id).where(CompanyStaff.company_id == response.json()["id"])
    )
    assert set(rows) == {world["anna"].id, world["boris"].id, world["helper"].id}


@pytest.mark.parametrize("enabled", [False, True])
async def test_reminders_go_to_all_accountants_and_assistants_by_setting(db, world, enabled):
    get_store().update({"notifications": {"assistant_reminders": enabled}})
    await assign(db, world["company"], world["boris"], world["helper"])
    await overdue_task(db, world["company"])
    settings = get_store().get()

    await planner.plan(db, settings, NOW)

    expected = {world["anna"].id, world["boris"].id}
    helpers = {world["helper"].id} if enabled else set()
    assert await queued(db, NotificationType.OVERDUE) == expected | helpers
    digests = await queued(db, NotificationType.DIGEST)
    assert (world["helper"].id in digests) == enabled
    assert world["spare"].id not in await queued(db, NotificationType.OVERDUE)
    own = await sender.digest_tasks(db, world["helper"], NOW.date())
    assert [task.title for task, _ in own] == ["Налог"]


@pytest.mark.parametrize("enabled", [False, True])
async def test_assistant_message_follows_setting_at_sending(db, world, enabled):
    await assign(db, world["company"], world["helper"])
    task = await overdue_task(db, world["company"])
    get_store().update({"notifications": {"assistant_reminders": enabled}})
    row = Notification(
        user_id=world["helper"].id,
        type=NotificationType.OVERDUE,
        scheduled_for=task.due_date,
        task_id=task.id,
    )
    db.add(row)
    await db.commit()

    message = await sender._compose(db, get_store().get(), world["helper"], [row], NOW.date())

    assert (message is not None) == enabled
    if enabled:
        assert "Налог" in message.text


async def test_substitute_replaces_only_the_absent_accountant(db, world):
    await assign(db, world["company"], world["boris"])
    carl = await make_user(db, 7)
    today = business_today()
    db.add(
        Substitution(
            accountant_id=world["anna"].id,
            substitute_id=carl.id,
            date_from=today,
            date_to=today,
            created_by=world["admin"].id,
        )
    )
    await db.commit()

    found = await payments.responsible(db, world["company"].id)

    assert {user.id for user in found} == {carl.id, world["boris"].id}
    assert world["company"].id in await get_accessible_company_ids(db, carl)


async def test_report_names_all_accountants_and_filters_by_each(client, db, world):
    await assign(db, world["company"], world["boris"])
    await overdue_task(db, world["company"])

    for name in ("anna", "boris"):
        response = await client.get(
            "/api/reports/completed",
            params={
                "from": "2026-10-01",
                "to": "2026-10-31",
                "accountant_id": world[name].id,
            },
            headers=auth(world["admin"]),
        )
        assert [row["accountant"] for row in response.json()["summary"]] == ["Анна, Борис"], name
