"""Напоминания о сроке электронной подписи."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.permissions import business_today
from app.core.settings_store import get_store
from app.models import AuditLog, Notification, Task
from app.services.notify.messages import days_word
from app.services.notify.planner import plan
from app.services.notify.sender import deliver
from app.services.tasks import regenerate_company
from tests.factories import auth
from tests.test_notifications import NOW, TODAY, bot, telegram, world  # noqa: F401

pytestmark = pytest.mark.usefixtures("secrets")


async def add(client, world, expires, notify_client=False, holder="Иванов И. И.") -> dict:  # noqa: F811
    response = await client.post(
        f"/api/companies/{world['company'].id}/signatures",
        json={"holder": holder, "expires_on": str(expires), "notify_client": notify_client},
        headers=auth(world["accountant"]),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def only_task(db) -> Task:
    return await db.scalar(select(Task).execution_options(populate_existing=True))


async def planned(db) -> list[tuple[int, int]]:
    """(кому, за сколько дней до срока) по напоминаниям о подписи."""
    due = (await only_task(db)).due_date
    rows = await db.scalars(select(Notification).where(Notification.type == "signature"))
    return sorted((row.user_id, (due - row.scheduled_for).days) for row in rows)


async def test_signature_creates_task_and_survives_generation(client, db, world):  # noqa: F811
    created = await add(client, world, business_today() + timedelta(days=100))

    await regenerate_company(db, world["company"].id)

    task = await db.scalar(select(Task).where(Task.signature_id == created["id"]))
    assert (task.title, task.kind, task.status, task.client_visible) == (
        "Истекает ЭЦП: Иванов И. И.",
        "other",
        "planned",
        False,
    )
    assert created["days_left"] == 100
    entry = await db.scalar(select(AuditLog))
    assert "Иванов" not in str(entry.payload)


async def test_renewal_reopens_task_and_delete_removes_it(client, db, world):  # noqa: F811
    created = await add(client, world, TODAY + timedelta(days=7))
    await plan(db, get_store().get(), NOW)
    task = await only_task(db)
    task.status = "done"
    await db.commit()
    url = f"/api/companies/{world['company'].id}/signatures/{created['id']}"
    headers = auth(world["accountant"])

    renewed = {"holder": "Петров", "expires_on": str(TODAY + timedelta(days=400))}
    assert (await client.patch(url, json=renewed, headers=headers)).status_code == 200

    task = await only_task(db)
    assert (task.status, task.title) == ("planned", "Истекает ЭЦП: Петров")
    assert task.due_date == TODAY + timedelta(days=400)
    assert await planned(db) == []
    assert (await client.delete(url, headers=headers)).status_code == 204
    assert await only_task(db) is None


@pytest.mark.parametrize(
    "request_body", [{"title": "Другое"}, {"due_date": "2027-05-05"}, {"client_visible": True}]
)
async def test_signature_task_is_changed_only_through_signature(client, db, world, request_body):  # noqa: F811
    await add(client, world, TODAY + timedelta(days=10))
    task = await only_task(db)
    headers = auth(world["accountant"])

    assert (
        await client.patch(f"/api/tasks/{task.id}", json=request_body, headers=headers)
    ).status_code == 422
    assert (await client.delete(f"/api/tasks/{task.id}", headers=headers)).status_code == 422
    done = await client.patch(f"/api/tasks/{task.id}", json={"status": "done"}, headers=headers)
    assert done.status_code == 200


@pytest.mark.parametrize(
    ("left", "threshold"),
    [(31, None), (30, 30), (20, 30), (14, 14), (8, 14), (7, 7), (1, 1), (0, 0)],
)
async def test_thresholds(client, db, world, left, threshold):  # noqa: F811
    await add(client, world, TODAY + timedelta(days=left))

    await plan(db, get_store().get(), NOW)
    await plan(db, get_store().get(), NOW)

    accountant = world["accountant"].id
    assert await planned(db) == ([] if threshold is None else [(accountant, threshold)])


async def test_client_gets_reminder_only_when_asked(client, db, world, telegram, bot):  # noqa: F811
    await add(client, world, TODAY + timedelta(days=14), notify_client=True)

    await plan(db, get_store().get(), NOW)
    await deliver(db, bot, get_store().get(), NOW, pause=0)

    people = {world[name].id for name in ("accountant", "payer", "viewer")}
    assert {user for user, _ in await planned(db)} == people
    texts = [text for _, text in telegram.sent if "ЭЦП" in text and "действует до" in text]
    assert len(texts) == 3
    assert texts[0].startswith("🟢 ООО «Ромашка»: Истекает ЭЦП")
    assert texts[0].endswith("действует до 10.12.2026, осталось 14 дней")


@pytest.mark.parametrize(
    ("count", "word"), [(1, "день"), (2, "дня"), (5, "дней"), (11, "дней"), (21, "день")]
)
def test_days_word(count, word):
    assert days_word(count) == word
