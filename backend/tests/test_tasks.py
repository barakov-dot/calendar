from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app import worker
from app.core.permissions import client_task_condition
from app.models import AuditLog, Patent, Role, Task
from app.services import tasks
from app.services.calendar.workdays import load_calendar, load_missing_years
from app.services.inn import with_check_digits
from app.worker import should_send, warning_text
from tests.factories import auth, link_client, make_company, make_user
from tests.rules_helpers import CALENDAR_DIR

TODAY = date(2026, 6, 15)
IP_INN = with_check_digits("0000000001")
YEAR = (date(2026, 1, 1), date(2026, 12, 31))


@pytest.fixture
async def calendar(db):
    await load_missing_years(db, CALENDAR_DIR)


@pytest.fixture
async def accountant(db):
    return await make_user(db, 2)


async def generate(db, company, today=TODAY, interval=YEAR) -> tasks.Result:
    result = await tasks.generate_tasks(db, company.id, *interval, await load_calendar(db), today)
    await db.commit()
    return result


async def all_tasks(db) -> dict[tuple, Task]:
    rows = await db.scalars(select(Task).execution_options(populate_existing=True))
    return {(t.rule_code, t.period_key, t.part): t for t in rows}


async def test_generation_is_idempotent(db, calendar, accountant):
    company = await make_company(db, accountant, has_employees=True)

    first = await generate(db, company)
    before = {key: (t.id, t.due_date, t.title) for key, t in (await all_tasks(db)).items()}
    second = await generate(db, company)

    assert first.created == len(before) > 50
    assert (second.created, second.updated, second.deleted, second.not_required) == (0, 0, 0, 0)
    after = {key: (t.id, t.due_date, t.title) for key, t in (await all_tasks(db)).items()}
    assert after == before


async def test_regeneration_keeps_status_amount_and_comments(db, calendar, accountant):
    company = await make_company(db, accountant)
    await generate(db, company)
    task = (await all_tasks(db))[("usn_advance", "2026-Q3", 1)]
    task.status, task.amount_kopecks = "paid", 12345
    task.comment, task.client_note = "внутренний", "клиенту"
    task.client_visible = False
    task.title, task.due_date = "старое", date(2026, 1, 1)
    await db.commit()

    result = await generate(db, company)

    task = (await all_tasks(db))[("usn_advance", "2026-Q3", 1)]
    assert result.updated == 1
    assert (task.title, task.due_date) == (
        "УСН: авансовый платёж за 9 месяцев 2026",
        date(2026, 10, 28),
    )
    assert (task.status, task.amount_kopecks) == ("paid", 12345)
    assert (task.comment, task.client_note, task.client_visible) == ("внутренний", "клиенту", False)


async def test_rule_stops_applying(db, calendar, accountant):
    company = await make_company(db, accountant)
    await generate(db, company)
    items = await all_tasks(db)
    items[("usn_advance", "2026-Q3", 1)].amount_kopecks = 100  # будущая с суммой
    items[("usn_notice", "2026-Q3", 1)].status = "done"  # будущая выполненная
    await db.commit()

    company.main_regime, company.nds_payer = "ausn_income", False
    await db.commit()
    result = await generate(db, company)

    items = await all_tasks(db)
    # прошлые остаются
    assert items[("usn_advance", "2026-Q1", 1)].status == "planned"
    # будущая пустая удалена, с суммой — «не требуется», выполненная не тронута
    assert ("usn_year_ooo", "2025", 1) in items
    assert ("usn_notice", "2026-Q1", 1) in items and items[
        ("usn_notice", "2026-Q3", 1)
    ].status == "done"
    changed = items[("usn_advance", "2026-Q3", 1)]
    assert (changed.status, changed.status_changed_by_role) == ("not_required", "system")
    assert changed.amount_kopecks == 100
    assert result.not_required == 1
    assert result.deleted >= 1
    assert ("ausn_tax", "2026-10", 1) in items

    # режим вернули — задача снова действует
    company.main_regime = "usn6"
    await db.commit()
    result = await generate(db, company)
    items = await all_tasks(db)
    assert items[("usn_advance", "2026-Q3", 1)].status == "planned"
    assert result.restored == 1


async def test_manual_not_required_is_not_restored(db, calendar, accountant):
    company = await make_company(db, accountant)
    await generate(db, company)
    task = (await all_tasks(db))[("usn_advance", "2026-Q3", 1)]
    task.status, task.status_changed_by_role = "not_required", "accountant"
    await db.commit()

    await generate(db, company)

    assert (await all_tasks(db))[("usn_advance", "2026-Q3", 1)].status == "not_required"


async def test_custom_tasks_are_never_touched(db, calendar, accountant):
    company = await make_company(db, accountant)
    db.add(
        Task(
            company_id=company.id,
            source="custom",
            kind="other",
            title="Своя",
            due_date=date(2026, 9, 1),
            original_due_date=date(2026, 9, 1),
        )
    )
    await db.commit()

    await generate(db, company)

    assert (None, None, 1) in await all_tasks(db)


async def test_archived_company_is_skipped(db, calendar, accountant):
    company = await make_company(db, accountant, is_archived=True)

    assert (await generate(db, company)).created == 0


async def test_new_calendar_moves_due_dates(db, accountant):
    company = await make_company(db, accountant)
    result = await generate(db, company)
    assert result.missing_calendar_years == {2026}
    # без календаря 9 января считается рабочим
    assert "Нет производственного календаря на 2026" in warning_text(result, TODAY)

    await load_missing_years(db, CALENDAR_DIR)
    result = await generate(db, company)

    assert result.missing_calendar_years == set()
    assert warning_text(result, TODAY) is None


async def test_years_without_rules_are_reported(db, calendar, accountant):
    company = await make_company(db, accountant)

    result = await generate(db, company, interval=(date(2027, 1, 1), date(2028, 3, 31)))

    assert result.missing_rule_years == {2028}
    # напоминаем незадолго до начала года, а не весь год
    # и про календарь 2028 года тоже: он ещё не опубликован
    assert warning_text(result, date(2027, 6, 15)) is None
    assert "правил на 2028" in warning_text(result, date(2027, 11, 26))


async def test_patent_amount_fills_only_empty(db, calendar, accountant):
    company = await make_company(db, accountant, entity_type="ip", inn=IP_INN)
    patent = Patent(company_id=company.id, date_start=date(2026, 1, 1), date_end=date(2026, 12, 31))
    db.add(patent)
    await db.commit()
    await generate(db, company)
    key = ("patent_payment", f"2026-P{patent.id}", 1)
    assert (await all_tasks(db))[key].amount_kopecks is None

    patent.cost_kopecks = 300
    await db.commit()
    await generate(db, company)
    assert (await all_tasks(db))[key].amount_kopecks == 100

    patent.cost_kopecks = 900
    await db.commit()
    await generate(db, company)
    assert (await all_tasks(db))[key].amount_kopecks == 100


def nds_parts(items, period="2026-Q2"):
    return [items[("nds_payment", period, part)] for part in (1, 2, 3)]


async def test_nds_split_override_and_paid(db, calendar, accountant):
    company = await make_company(db, accountant, main_regime="osno", nds_payer=True)
    await generate(db, company)

    await tasks.set_nds_amount(db, accountant, company, "2026-Q2", 100_000_00)
    parts = nds_parts(await all_tasks(db))
    assert [p.amount_kopecks for p in parts] == [33_333_33, 33_333_33, 33_333_34]
    assert not any(p.amount_overridden for p in parts)

    tasks.override_amount(parts[0], 500)
    parts[1].status = "paid"
    await db.commit()
    await tasks.set_nds_amount(db, accountant, company, "2026-Q2", 300)

    parts = nds_parts(await all_tasks(db))
    assert [p.amount_kopecks for p in parts] == [500, 33_333_33, 100]
    await generate(db, company)
    assert [p.amount_kopecks for p in nds_parts(await all_tasks(db))] == [500, 33_333_33, 100]
    last = (await db.scalars(select(AuditLog).order_by(AuditLog.id.desc()))).first()
    assert last.payload == {"period": "2026-Q2", "total_kopecks": 300, "parts": [3]}


@pytest.mark.usefixtures("secrets")
async def test_nds_endpoint_access(client, db, calendar, accountant):
    stranger = await make_user(db, 3)
    client_user = await make_user(db, 4, Role.CLIENT)
    company = await make_company(db, accountant, main_regime="osno", nds_payer=True)
    await link_client(db, company, client_user, can_mark_paid=True)
    await generate(db, company)
    url = f"/api/tasks/nds/{company.id}/2026-Q2"
    body = {"amount_kopecks": 900}

    assert (await client.put(url, json=body)).status_code == 401
    assert (await client.put(url, json=body, headers=auth(client_user))).status_code == 403
    assert (await client.put(url, json=body, headers=auth(stranger))).status_code == 404
    assert all(p.amount_kopecks is None for p in nds_parts(await all_tasks(db)))
    response = await client.put(url, json=body, headers=auth(accountant))
    assert [p["amount_kopecks"] for p in response.json()] == [300, 300, 300]

    missing = f"/api/tasks/nds/{company.id}/2030-Q1"
    assert (await client.put(missing, json=body, headers=auth(accountant))).status_code == 404
    for bad in ({"amount_kopecks": -1}, {"amount_kopecks": 1.5}, {}):
        assert (await client.put(url, json=bad, headers=auth(accountant))).status_code == 422


@pytest.mark.usefixtures("secrets")
async def test_company_changes_regenerate_tasks(client, db, calendar, accountant, monkeypatch):
    monkeypatch.setattr(tasks, "today", lambda: TODAY)
    headers = auth(accountant)
    created = await client.post(
        "/api/companies",
        json={
            "company": {
                "inn": IP_INN,
                "name": "ИП Тест",
                "entity_type": "ip",
                "main_regime": "usn6",
            }
        },
        headers=headers,
    )
    assert created.status_code == 201, created.json()
    company_id = created.json()["id"]
    assert ("usn_advance", "2026-Q3", 1) in await all_tasks(db)

    await client.patch(
        f"/api/companies/{company_id}",
        json={"company": {"has_employees": True}},
        headers=headers,
    )
    assert ("insurance_payment", "2026-09", 1) in await all_tasks(db)

    url = f"/api/companies/{company_id}/patents"
    patent = await client.post(
        url,
        json={"date_start": "2026-07-01", "date_end": "2026-09-30", "cost_kopecks": 5},
        headers=headers,
    )
    key = ("patent_payment", f"2026-P{patent.json()['id']}", 1)
    assert (await all_tasks(db))[key].amount_kopecks == 5

    # будущий патент удалён — его платёж без изменений бухгалтера тоже,
    # а с суммой остаётся как «не требуется»
    await client.delete(f"{url}/{patent.json()['id']}", headers=headers)
    assert (await all_tasks(db))[key].status == "not_required"


async def test_failed_generation_does_not_lose_company(
    client, db, accountant, secrets, monkeypatch
):
    async def broken(*_):
        raise RuntimeError("сбой")

    monkeypatch.setattr(tasks, "regenerate_company", broken)

    response = await client.post(
        "/api/companies",
        json={
            "company": {
                "inn": IP_INN,
                "name": "ИП Тест",
                "entity_type": "ip",
                "main_regime": "usn6",
            }
        },
        headers=auth(accountant),
    )

    assert response.status_code == 201


def test_same_warning_is_not_repeated_daily(monkeypatch):
    now = datetime(2026, 11, 26, tzinfo=UTC)
    monkeypatch.setattr(worker, "_sent", {"текст": now})

    assert should_send("другой", now)
    assert not should_send("текст", now + timedelta(days=6))
    assert should_send("текст", now + timedelta(days=7))


@pytest.mark.parametrize(
    ("show", "kinds"),
    [(True, {"payment", "notice", "report"}), (False, {"payment", "report"})],
)
async def test_client_visibility_of_notices(db, calendar, accountant, show, kinds):
    company = await make_company(db, accountant)
    await generate(db, company)
    hidden = (await all_tasks(db))[("usn_advance", "2026-Q1", 1)]
    hidden.client_visible = False
    await db.commit()

    found = (await db.scalars(select(Task).where(client_task_condition(show)))).all()

    assert {task.kind for task in found} == kinds
    assert hidden.id not in {task.id for task in found}
