from datetime import date

import pytest
from sqlalchemy import select

from app.core.settings_store import get_store
from app.models import AuditLog, Role, Task
from app.services import tasks
from app.services.calendar.workdays import load_missing_years
from tests.factories import assign, auth, link_client, make_company, make_user
from tests.rules_helpers import CALENDAR_DIR

pytestmark = pytest.mark.usefixtures("secrets")
TODAY = date(2026, 6, 15)


@pytest.fixture
async def world(db, monkeypatch):
    monkeypatch.setattr(tasks, "today", lambda: TODAY)
    await load_missing_years(db, CALENDAR_DIR)
    admin = await make_user(db, 1, Role.ADMIN)
    helper = await make_user(db, 6, Role.ASSISTANT)
    first = await make_user(db, 2, first_name="Борис")
    second = await make_user(db, 3)
    payer = await make_user(db, 4, Role.CLIENT)
    own = await make_company(db, first, 1, short_name="Своя", main_regime="osno", nds_payer=True)
    other = await make_company(db, second, 2, short_name="Чужая")
    await assign(db, own, helper)
    await link_client(db, own, payer, can_mark_paid=True)
    for company in (own, other):
        await tasks.regenerate_company(db, company.id)
    return locals()


async def task_of(db, company, code: str, period: str, part: int = 1) -> Task:
    return await db.scalar(
        select(Task)
        .where(
            Task.company_id == company.id,
            Task.rule_code == code,
            Task.period_key == period,
            Task.part == part,
        )
        .execution_options(populate_existing=True)
    )


async def listed(client, user, **params) -> dict:
    response = await client.get("/api/tasks", params=params, headers=auth(user))
    assert response.status_code == 200, response.json()
    return response.json()


@pytest.mark.parametrize(
    ("user", "companies"),
    [
        ("admin", {"Своя", "Чужая"}),
        ("helper", {"Своя"}),
        ("first", {"Своя"}),
        ("second", {"Чужая"}),
        ("payer", {"Своя"}),
    ],
)
async def test_list_is_limited_by_access(client, world, user, companies):
    body = await listed(client, world[user], limit=2000)

    assert {item["company_name"] for item in body["items"]} == companies
    assert body["total"] == len(body["items"])
    assert body["today"] == "2026-06-15"
    foreign = await listed(client, world[user], company_id=world["other"].id)
    assert bool(foreign["items"]) == ("Чужая" in companies)


async def test_client_gets_only_visible_tasks_without_internal_fields(client, db, world):
    own = world["own"]
    hidden = await task_of(db, own, "usn_advance", "2026-Q1") or await task_of(
        db, own, "nds_payment", "2026-Q1"
    )
    hidden.client_visible = False
    visible = await task_of(db, own, "nds_payment", "2026-Q2")
    visible.comment, visible.client_note = "тайна", "для клиента"
    await db.commit()
    payer = world["payer"]

    body = await listed(client, payer, limit=2000)
    detail = await client.get(f"/api/tasks/{visible.id}", headers=auth(payer))

    public = {
        "id",
        "company_id",
        "company_name",
        "kind",
        "title",
        "due_date",
        "amount_kopecks",
        "status",
        "client_note",
        "source_ref",
        "has_files",
        "before_start",
        "can_mark_paid",
        "can_unmark_paid",
    }
    assert all(set(item) == public for item in body["items"])
    assert set(detail.json()) == public
    assert "тайна" not in detail.text
    assert hidden.id not in {item["id"] for item in body["items"]}
    assert (await client.get(f"/api/tasks/{hidden.id}", headers=auth(payer))).status_code == 404

    get_store().update({"tasks": {"show_notices_to_clients": False}})
    body = await listed(client, payer, limit=2000)
    assert "notice" not in {item["kind"] for item in body["items"]}


async def test_filters_and_pages(client, db, world):
    first = world["first"]
    params = {"from": "2026-07-01", "to": "2026-07-31", "kind": "payment", "status": "planned"}

    body = await listed(client, first, **params)

    assert body["items"]
    assert all(
        item["kind"] == "payment" and item["due_date"].startswith("2026-07")
        for item in body["items"]
    )
    page = await listed(client, first, limit=1, offset=1, **params)
    assert page["total"] == body["total"]
    assert page["items"] == body["items"][1:2]
    both = await listed(client, first, kind=["payment", "report"], limit=2000)
    assert {item["kind"] for item in both["items"]} == {"payment", "report"}
    missing = await listed(client, first, missing_amount=True, limit=2000)
    assert all(item["needs_amount"] for item in missing["items"])


FOREIGN = [
    ("PATCH", "/api/tasks/{id}", {"status": "not_required"}),
    ("DELETE", "/api/tasks/{id}", None),
    ("POST", "/api/tasks/bulk", {"ids": ["{id}"], "status": "not_required"}),
]


@pytest.mark.parametrize(("method", "path", "body"), FOREIGN)
async def test_only_responsible_staff_change_tasks(client, db, world, method, path, body):
    task = await task_of(db, world["own"], "nds_payment", "2026-Q2")
    if body and "ids" in body:
        body = body | {"ids": [task.id]}
    url = path.format(id=task.id)

    assert (await client.request(method, url, json=body)).status_code == 401
    for name, code in (("second", 404), ("helper", 403), ("payer", 403)):
        response = await client.request(method, url, json=body, headers=auth(world[name]))
        assert response.status_code == code, name

    after = await task_of(db, world["own"], "nds_payment", "2026-Q2")
    assert after is not None and after.status == "planned"


async def test_foreign_read(client, db, world):
    task = await task_of(db, world["own"], "nds_payment", "2026-Q2")
    url = f"/api/tasks/{task.id}"

    assert (await client.get(url, headers=auth(world["second"]))).status_code == 404
    assert (await client.get(url, headers=auth(world["helper"]))).status_code == 200
    create = {"company_id": world["own"].id, "title": "x", "due_date": "2026-07-01"}
    for name, code in (("second", 404), ("helper", 403), ("payer", 403)):
        response = await client.post("/api/tasks", json=create, headers=auth(world[name]))
        assert response.status_code == code, name


async def test_status_amount_and_comments(client, db, world):
    task = await task_of(db, world["own"], "nds_payment", "2026-Q2", 2)
    url = f"/api/tasks/{task.id}"
    headers = auth(world["first"])

    response = await client.patch(
        url,
        json={
            "status": "paid",
            "amount_kopecks": 12345,
            "comment": "внутренний",
            "client_note": "клиенту",
            "client_visible": False,
        },
        headers=headers,
    )

    body = response.json()
    assert (body["status"], body["status_changed_by_name"]) == ("paid", "Борис")
    assert body["status_changed_by_role"] == "accountant"
    assert (body["amount_kopecks"], body["amount_overridden"]) == (12345, True)
    assert [part["part"] for part in body["nds_parts"]] == [1, 2, 3]
    entry = (await db.scalars(select(AuditLog).order_by(AuditLog.id.desc()))).first()
    assert entry.payload["changes"]["comment"] is None  # тексты в журнал не пишутся
    cleared = await client.patch(url, json={"amount_kopecks": None}, headers=headers)
    assert cleared.json()["amount_kopecks"] is None
    # повтор тех же значений в журнал не попадает
    before = len((await db.scalars(select(AuditLog))).all())
    await client.patch(url, json={"status": "paid"}, headers=headers)
    assert len((await db.scalars(select(AuditLog))).all()) == before


@pytest.mark.parametrize(
    ("code", "body"),
    [
        ("nds_payment", {"status": "done"}),
        ("nds_declaration", {"status": "paid"}),
        ("nds_declaration", {"amount_kopecks": 1}),
        ("nds_declaration", {"title": "другое"}),
        ("nds_declaration", {"status": None}),
        ("nds_declaration", {"due_date": None}),
        ("nds_declaration", {"due_date": "2026-08-01", "reset_due": True}),
        ("nds_payment", {"amount_kopecks": -1}),
        ("nds_payment", {"company_id": 2}),
    ],
)
async def test_invalid_changes(client, db, world, code, body):
    task = await task_of(db, world["own"], code, "2026-Q2")

    response = await client.patch(f"/api/tasks/{task.id}", json=body, headers=auth(world["first"]))

    assert response.status_code == 422, response.json()


async def test_manual_due_date_survives_generation_and_can_be_reset(client, db, world):
    own = world["own"]
    task = await task_of(db, own, "nds_declaration", "2026-Q2")
    original = task.due_date
    url = f"/api/tasks/{task.id}"
    headers = auth(world["first"])

    moved = await client.patch(url, json={"due_date": "2026-08-03"}, headers=headers)
    assert moved.json()["due_overridden"] is True
    await tasks.regenerate_company(db, own.id)
    task = await task_of(db, own, "nds_declaration", "2026-Q2")
    assert task.due_date == date(2026, 8, 3)

    # правило перестало подходить — задача с ручным сроком остаётся «не требуется»
    own.nds_payer = False
    await db.commit()
    await tasks.regenerate_company(db, own.id)
    task = await task_of(db, own, "nds_declaration", "2026-Q2")
    assert task.status == "not_required"

    reset = await client.patch(url, json={"reset_due": True}, headers=headers)
    assert (reset.json()["due_date"], reset.json()["due_overridden"]) == (
        original.isoformat(),
        False,
    )


async def test_bulk(client, db, world):
    own = world["own"]
    payments = [await task_of(db, own, "nds_payment", "2026-Q2", part) for part in (1, 2, 3)]
    report = await task_of(db, own, "nds_declaration", "2026-Q2")
    ids = [task.id for task in (*payments, report)]
    headers = auth(world["first"])

    response = await client.post(
        "/api/tasks/bulk", json={"ids": ids, "status": "paid"}, headers=headers
    )

    assert response.json() == {"updated": 3, "skipped": 1}
    again = await client.post(
        "/api/tasks/bulk", json={"ids": ids, "status": "paid"}, headers=headers
    )
    assert again.json() == {"updated": 0, "skipped": 4}


async def test_bulk_with_foreign_task_changes_nothing(client, db, world):
    mine = await task_of(db, world["own"], "nds_payment", "2026-Q2")
    foreign = await task_of(db, world["other"], "usn_advance", "2026-Q2")

    response = await client.post(
        "/api/tasks/bulk",
        json={"ids": [mine.id, foreign.id], "status": "paid"},
        headers=auth(world["first"]),
    )

    assert response.status_code == 404
    assert (await task_of(db, world["own"], "nds_payment", "2026-Q2")).status == "planned"


async def test_custom_task_lifecycle(client, db, world):
    headers = auth(world["first"])
    created = await client.post(
        "/api/tasks",
        json={
            "company_id": world["own"].id,
            "title": "Подписать акт",
            "due_date": "2026-07-04",
        },
        headers=headers,
    )
    body = created.json()
    assert (body["source"], body["client_visible"]) == ("custom", False)
    url = f"/api/tasks/{body['id']}"
    edited = await client.patch(
        url, json={"title": "Акт", "due_date": "2026-07-10"}, headers=headers
    )
    assert edited.json()["title"] == "Акт"
    await tasks.regenerate_company(db, world["own"].id)
    assert (await client.get(url, headers=headers)).status_code == 200
    assert (await client.delete(url, headers=headers)).status_code == 204

    rule_task = await task_of(db, world["own"], "nds_payment", "2026-Q2")
    response = await client.delete(f"/api/tasks/{rule_task.id}", headers=headers)
    assert response.status_code == 422


async def test_personal_task(client, world):
    first = auth(world["first"])
    created = await client.post(
        "/api/tasks",
        json={"title": "Позвонить", "due_date": "2026-07-01", "client_visible": True},
        headers=first,
    )
    body = created.json()
    assert (body["company_id"], body["company_name"]) == (None, "Личная задача")
    assert body["client_visible"] is False

    seen = {}
    for name in ("admin", "helper", "first", "second", "payer"):
        found = await listed(client, world[name], personal=True)
        seen[name] = bool(found["items"])
    assert seen == {
        "admin": True,
        "helper": False,
        "first": True,
        "second": False,
        "payer": False,
    }
    url = f"/api/tasks/{body['id']}"
    for name, code in (("second", 404), ("helper", 403)):
        response = await client.patch(url, json={"status": "done"}, headers=auth(world[name]))
        assert response.status_code == code
    response = await client.patch(url, json={"client_visible": True}, headers=first)
    assert response.status_code == 422


async def test_archived_company_hidden_from_common_list(client, db, world):
    world["own"].is_archived = True
    await db.commit()

    common = await listed(client, world["first"], limit=2000)
    card = await listed(client, world["first"], company_id=world["own"].id)

    assert common["items"] == []
    assert card["items"]


async def test_companies_show_missing_amount(client, db, world):
    headers = auth(world["first"])

    [item] = (await client.get("/api/companies", headers=headers)).json()
    assert item["has_missing_amount"] is True

    soon = (await db.scalars(select(Task).where(Task.needs_amount.is_(True)))).all()
    for task in soon:
        task.amount_kopecks = 1
    await db.commit()
    [item] = (await client.get("/api/companies", headers=headers)).json()
    assert item["has_missing_amount"] is False


async def test_mine_returns_only_own_personal_tasks(client, db, world):
    for user, title in ((world["admin"], "дело админа"), (world["first"], "дело бухгалтера")):
        created = await client.post(
            "/api/tasks", headers=auth(user), json={"title": title, "due_date": "2026-12-01"}
        )
        assert created.status_code == 201

    async def titles(user, query):
        response = await client.get(f"/api/tasks?{query}", headers=auth(user))
        return sorted(item["title"] for item in response.json()["items"])

    # админ видит все личные задачи, но «мои дела» — только свои
    assert await titles(world["admin"], "personal=true") == ["дело админа", "дело бухгалтера"]
    assert await titles(world["admin"], "mine=true") == ["дело админа"]
    assert await titles(world["first"], "mine=true") == ["дело бухгалтера"]


async def test_newest_first_reverses_dates(client, world):
    dates = [
        item["due_date"]
        for item in (await listed(client, world["first"], newest_first=True, limit=2000))["items"]
    ]

    assert dates == sorted(dates, reverse=True) and len(set(dates)) > 1
