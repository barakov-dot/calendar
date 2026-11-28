from datetime import date

import pytest
from sqlalchemy import select

from app.models import RecurringReminder, Role, Task
from app.services import reminders, tasks
from app.services.calendar.workdays import load_missing_years
from app.services.reminders import Schedule, occurrence_dates, shift
from tests.factories import assign, auth, make_company, make_user
from tests.rules_helpers import CALENDAR_DIR, work_calendar

TODAY = date(2026, 11, 20)


def monthly(day: int) -> Schedule:
    return Schedule(frequency="monthly", day_of_month=day)


@pytest.mark.parametrize(
    ("schedule", "start", "expected"),
    [
        (monthly(10), date(2026, 1, 15), ["2026-02-10", "2026-03-10", "2026-04-10"]),
        # нет такого числа — последний день месяца
        (monthly(31), date(2026, 1, 1), ["2026-01-31", "2026-02-28", "2026-03-31"]),
        (
            Schedule(frequency="quarterly", day_of_month=5),
            date(2026, 2, 1),
            ["2026-02-05", "2026-05-05", "2026-08-05"],
        ),
        (
            Schedule(frequency="yearly", day_of_month=29),
            date(2028, 2, 1),
            ["2028-02-29", "2029-02-28", "2030-02-28"],
        ),
        (
            Schedule(frequency="weekly", interval_weeks=2),
            date(2026, 1, 5),
            ["2026-01-05", "2026-01-19", "2026-02-02"],
        ),
    ],
)
def test_dates(schedule, start, expected):
    found = occurrence_dates(schedule, start, None, start, date(2031, 1, 1))

    assert [next(found).isoformat() for _ in range(3)] == expected
    assert Schedule.from_rrule(schedule.to_rrule()) == schedule


def test_until_and_window():
    found = occurrence_dates(
        monthly(10), date(2026, 1, 1), date(2026, 4, 30), date(2026, 3, 1), date(2027, 1, 1)
    )

    assert [day.month for day in found] == [3, 4]


@pytest.mark.parametrize(
    "bad",
    [
        {"frequency": "monthly"},
        {"frequency": "weekly"},
        {"frequency": "daily"},
        {"frequency": "monthly", "day_of_month": 32},
        {"frequency": "weekly", "interval_weeks": 0},
    ],
)
def test_invalid_schedule(bad):
    with pytest.raises(ValueError):
        Schedule.model_validate(bad)


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ("none", date(2026, 5, 9)),
        ("next_workday", date(2026, 5, 12)),
        ("prev_workday", date(2026, 5, 8)),
    ],
)
def test_shift(rule, expected):
    assert shift(date(2026, 5, 9), rule, work_calendar()) == expected


@pytest.fixture
async def world(db, secrets, monkeypatch):
    monkeypatch.setattr(tasks, "today", lambda: TODAY)
    await load_missing_years(db, CALENDAR_DIR)
    admin = await make_user(db, 1, Role.ADMIN)
    helper = await make_user(db, 6, Role.ASSISTANT)
    first = await make_user(db, 2)
    second = await make_user(db, 3)
    payer = await make_user(db, 4, Role.CLIENT)
    company = await make_company(db, first)
    await assign(db, company, helper)
    return locals()


def body(company_id=None, **extra) -> dict:
    return {
        "company_id": company_id,
        "title": "Отправить акт",
        "kind": "other",
        "schedule": {"frequency": "monthly", "day_of_month": 28},
        "dtstart": "2026-01-01",
        "shift_rule": "next_workday",
        "audience": "both",
    } | extra


async def instances(db) -> list[Task]:
    return list(
        await db.scalars(
            select(Task)
            .where(Task.source == "custom")
            .order_by(Task.original_due_date)
            .execution_options(populate_existing=True)
        )
    )


async def test_create_expands_60_days_and_is_idempotent(client, db, world):
    headers = auth(world["first"])

    response = await client.post("/api/reminders", json=body(world["company"].id), headers=headers)

    assert response.status_code == 201, response.json()
    found = await instances(db)
    # с 20.11 по 19.01: ноябрь (суббота → понедельник) и декабрь
    assert [(t.original_due_date, t.due_date) for t in found] == [
        (date(2026, 11, 28), date(2026, 11, 30)),
        (date(2026, 12, 28), date(2026, 12, 28)),
    ]
    assert all(t.client_visible and t.company_id == world["company"].id for t in found)
    assert response.json()["next_dates"][0] == "2026-11-30"
    for _ in range(2):
        await tasks.regenerate_all(db)
    assert len([t for t in await instances(db)]) == 2


async def test_edit_replaces_only_untouched_future_tasks(client, db, world):
    headers = auth(world["first"])
    created = await client.post("/api/reminders", json=body(world["company"].id), headers=headers)
    first_task, second_task = await instances(db)
    first_task.comment = "уже в работе"
    await db.commit()
    url = f"/api/reminders/{created.json()['id']}"

    changed = body(
        world["company"].id,
        title="Новое",
        schedule={"frequency": "monthly", "day_of_month": 5},
        audience="accountant",
    )
    assert (await client.patch(url, json=changed, headers=headers)).status_code == 200

    found = await instances(db)
    assert [(t.title, t.original_due_date.isoformat()) for t in found] == [
        ("Отправить акт", "2026-11-28"),  # изменённая осталась
        ("Новое", "2026-12-05"),
        ("Новое", "2027-01-05"),
    ]
    assert found[1].client_visible is False

    assert (await client.delete(url, headers=headers)).status_code == 204
    found = await instances(db)
    assert [t.title for t in found] == ["Отправить акт"]
    assert found[0].recurring_reminder_id is None


async def test_pause(client, db, world):
    headers = auth(world["first"])
    created = await client.post("/api/reminders", json=body(world["company"].id), headers=headers)
    url = f"/api/reminders/{created.json()['id']}"

    await client.patch(url, json=body(world["company"].id, is_active=False), headers=headers)
    await tasks.regenerate_all(db)

    assert await instances(db) == []


@pytest.mark.parametrize(("until", "continues"), [(None, True), ("2026-12-31", False)])
async def test_endless_reminder_keeps_going(client, db, world, monkeypatch, until, continues):
    data = body(world["company"].id, kind="payment", title="Аренда", until=until)
    response = await client.post("/api/reminders", json=data, headers=auth(world["first"]))
    assert response.status_code == 201, response.text

    # ночная генерация через год
    monkeypatch.setattr(tasks, "today", lambda: date(2027, 11, 20))
    await tasks.regenerate_all(db)

    dates = [task.original_due_date for task in await instances(db)]
    assert (date(2027, 11, 28) in dates and date(2027, 12, 28) in dates) == continues
    assert (max(dates) > date(2026, 12, 31)) == continues


async def test_amount_goes_to_tasks_and_follows_changes(client, db, world):
    headers = auth(world["first"])
    data = body(world["company"].id, kind="payment", title="Аренда", amount_kopecks=25_000_00)

    created = await client.post("/api/reminders", json=data, headers=headers)

    assert created.json()["amount_kopecks"] == 25_000_00, created.text
    first, second = (await instances(db))[:2]
    assert [(t.amount_kopecks, t.needs_amount) for t in (first, second)] == [(25_000_00, True)] * 2
    # сумму одной задачи изменили вручную: она остаётся как есть
    edited = await client.patch(
        f"/api/tasks/{first.id}", json={"amount_kopecks": 100_00}, headers=headers
    )
    assert edited.status_code == 200, edited.text

    url = f"/api/reminders/{created.json()['id']}"
    await client.patch(url, json=data | {"amount_kopecks": 150_000_00}, headers=headers)

    amounts = [task.amount_kopecks for task in await instances(db)]
    assert amounts[0] == 100_00 and set(amounts[1:]) == {150_000_00}

    await client.delete(url, headers=headers)
    assert [task.amount_kopecks for task in await instances(db)] == [100_00]


async def test_amount_is_added_to_existing_reminder(client, db, world):
    headers = auth(world["first"])
    data = body(world["company"].id, kind="payment")
    created = await client.post("/api/reminders", json=data, headers=headers)

    await client.patch(
        f"/api/reminders/{created.json()['id']}",
        json=data | {"amount_kopecks": 500_00},
        headers=headers,
    )

    assert {task.amount_kopecks for task in await instances(db)} == {500_00}


@pytest.mark.parametrize(("kind", "stored"), [("other", 100), ("report", None)])
async def test_amount_only_where_it_makes_sense(client, world, kind, stored):
    data = body(world["company"].id, kind=kind, amount_kopecks=100)

    response = await client.post("/api/reminders", json=data, headers=auth(world["first"]))

    assert response.json()["amount_kopecks"] == stored


async def test_personal_reminder_and_access(client, db, world):
    first = auth(world["first"])
    personal = await client.post("/api/reminders", json=body(), headers=first)
    of_company = await client.post("/api/reminders", json=body(world["company"].id), headers=first)
    assert personal.json()["audience"] == "accountant"
    assert personal.json()["company_name"] == "Личное"
    owners = {(t.company_id, t.owner_id) for t in await instances(db)}
    assert owners == {(None, world["first"].id), (world["company"].id, None)}
    await tasks.regenerate_all(db)
    assert len(await instances(db)) == 4

    async def visible(name):
        response = await client.get("/api/reminders", headers=auth(world[name]))
        return response.status_code, len(response.json()) if response.is_success else None

    assert await visible("admin") == (200, 2)
    # чужие личные напоминания помощник не видит
    assert await visible("helper") == (200, 1)
    assert await visible("second") == (200, 0)
    assert (await visible("payer"))[0] == 403
    for reminder in (personal, of_company):
        url = f"/api/reminders/{reminder.json()['id']}"
        for name, code in (("second", 404), ("helper", 403), ("payer", 403)):
            headers = auth(world[name])
            assert (await client.delete(url, headers=headers)).status_code == code
    response = await client.post(
        "/api/reminders", json=body(world["company"].id), headers=auth(world["second"])
    )
    assert response.status_code == 404
    assert len((await db.scalars(select(RecurringReminder))).all()) == 2


async def test_invalid_reminder(client, world):
    headers = auth(world["first"])

    early = await client.post("/api/reminders", json=body(until="2025-01-01"), headers=headers)
    bad = await client.post(
        "/api/reminders", json=body(schedule={"frequency": "weekly"}), headers=headers
    )

    assert (early.status_code, bad.status_code) == (422, 422)


async def test_calendar_change_moves_future_instances(db, world):
    reminder = RecurringReminder(
        company_id=world["company"].id,
        created_by=world["first"].id,
        title="x",
        kind="other",
        rrule=monthly(31).to_rrule(),
        dtstart=date(2026, 12, 1),
        shift_rule="next_workday",
        audience="accountant",
    )
    db.add(reminder)
    await db.flush()
    from app.services.calendar.workdays import WorkCalendar

    await reminders.expand(db, reminder, WorkCalendar({}), TODAY)
    assert (await instances(db))[0].due_date == date(2026, 12, 31)

    await reminders.expand(db, reminder, work_calendar(), TODAY)

    assert (await instances(db))[0].due_date == date(2027, 1, 11)
