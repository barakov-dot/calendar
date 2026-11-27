"""Дата начала ведения календаря: прежние сроки не просрочены и молчат, но меняются."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.settings_store import get_store
from app.models import Notification, Role, TaskStatus
from app.services import reports, tasks
from app.services.declarations.parser import parse
from app.services.inn import with_check_digits
from app.services.notify.planner import plan
from app.services.notify.sender import digest_tasks
from tests.factories import auth, link_client, make_company, make_user
from tests.test_declarations import nds, send, vat_tasks
from tests.test_payments import make_task

pytestmark = pytest.mark.usefixtures("secrets")

START = date(2026, 11, 1)
TODAY = date(2026, 11, 3)


def rule(code, due, **fields):
    return {
        "source": "rule",
        "rule_code": code,
        "period_key": str(due),
        "due_date": due,
        "original_due_date": due,
        "needs_amount": True,
    } | fields


@pytest.fixture
async def world(db):
    accountant = await make_user(db, 2)
    client_user = await make_user(db, 3, Role.CLIENT)
    company = await make_company(db, accountant, 1, calendar_start=START)
    await link_client(db, company, client_user, can_mark_paid=True)
    old = await make_task(db, company, **rule("a", date(2026, 10, 31)))
    fresh = await make_task(db, company, **rule("b", date(2026, 11, 2)))
    # заведённая человеком задача остаётся просроченной
    own = await make_task(
        db, company, due_date=date(2026, 10, 30), original_due_date=date(2026, 10, 30)
    )
    return locals()


async def test_list_marks_and_hides_history(client, world):
    headers = auth(world["accountant"])
    late = {"status": "planned", "to": "2026-11-02"}

    everything = await client.get("/api/tasks", params=late, headers=headers)
    active = await client.get("/api/tasks", params=late | {"hide_history": True}, headers=headers)

    flags = {item["id"]: item["before_start"] for item in everything.json()["items"]}
    assert flags == {world["old"].id: True, world["fresh"].id: False, world["own"].id: False}
    assert active.json()["total"] == 2


async def test_history_stays_editable(client, db, world):
    response = await client.patch(
        f"/api/tasks/{world['old'].id}",
        json={"amount_kopecks": 100, "status": "paid"},
        headers=auth(world["accountant"]),
    )

    assert response.status_code == 200, response.json()


async def test_no_reminders_digest_or_report_about_history(db, world):
    await plan(db, get_store().get(), datetime(2026, 11, 3, 7, 0, tzinfo=UTC))

    reminded = set(
        await db.scalars(select(Notification.task_id).where(Notification.task_id.is_not(None)))
    )
    assert world["old"].id not in reminded and world["fresh"].id in reminded
    digest = await digest_tasks(db, world["accountant"], TODAY)
    assert {task.id for task, _ in digest} == {world["fresh"].id, world["own"].id}
    report = await reports.build(
        db, world["accountant"], date(2026, 10, 1), date(2026, 11, 30), TODAY
    )
    assert report.summary[0].overdue == 2


async def test_without_start_date_everything_counts(client, db, world):
    world["company"].calendar_start = None
    await db.commit()

    listed = await client.get(
        "/api/tasks",
        params={"to": "2026-11-02", "hide_history": True},
        headers=auth(world["accountant"]),
    )

    assert listed.json()["total"] == 3


async def test_start_date_is_set_in_company_card(client, db, world):
    url = f"/api/companies/{world['company'].id}"
    headers = auth(world["accountant"])
    # make_company создаёт ИНН с проверочными цифрами для ООО
    response = await client.patch(
        url, json={"company": {"calendar_start": "2026-12-01"}}, headers=headers
    )

    assert response.status_code == 200, response.json()
    assert response.json()["calendar_start"] == "2026-12-01"


async def test_declaration_fills_paid_payment_without_amount(client, db, world):
    parts = await vat_tasks(db, world["company"], status=TaskStatus.PAID)

    response = await send(client, world["accountant"], nds(inn=world["company"].inn), "apply")

    assert parse(nds()).items and response.status_code == 200, response.text
    assert [part["kept"] for part in response.json()["parts"]] == ["", "", ""]
    await db.refresh(parts[1])
    assert (parts[1].status, parts[1].amount_kopecks) == ("paid", 33_334_00)


async def test_new_company_has_no_missed_tasks(client, db, world):
    headers = auth(world["accountant"])
    data = {
        "inn": with_check_digits("000000099"),
        "name": "ООО «Новая»",
        "entity_type": "ooo",
        "main_regime": "osno",
        "calendar_start": str(tasks.today()),
    }

    created = await client.post("/api/companies", json={"company": data}, headers=headers)

    assert created.status_code == 201, created.json()
    company_id = created.json()["id"]
    yesterday = str(tasks.today() - timedelta(days=1))
    late = {"company_id": company_id, "status": "planned", "to": yesterday}
    everything = await client.get("/api/tasks", params=late, headers=headers)
    active = await client.get("/api/tasks", params=late | {"hide_history": True}, headers=headers)
    assert all(item["before_start"] for item in everything.json()["items"])
    assert active.json()["total"] == 0
