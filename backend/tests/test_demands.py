"""Требования инспекции. Все документы и сведения в тестах выдуманы."""

from datetime import UTC, date, datetime
from urllib.parse import quote

import pytest
from fpdf import FPDF
from sqlalchemy import select

from app.core.config import get_config
from app.core.settings_store import get_store
from app.models import Demand, Notification, Role, Task
from app.services.calendar.workdays import load_calendar, load_missing_years
from app.services.demands.recognize import pdf_text, read
from app.services.demands.types import add_workdays, get_book
from app.services.notify.planner import plan
from app.services.notify.sender import deliver
from app.services.reports import FONTS
from app.services.telegram.factory import create_bot
from tests.factories import auth, link_client, make_company, make_user
from tests.fakes import FakeTelegram
from tests.test_tasks import CALENDAR_DIR

pytestmark = pytest.mark.usefixtures("secrets")


def pdf(*lines: str) -> bytes:
    document = FPDF()
    document.add_page()
    document.add_font("DejaVu", "", FONTS / "DejaVuSans.ttf")
    document.set_font("DejaVu", "", 9)
    for line in lines:
        document.multi_cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
    return bytes(document.output())


@pytest.fixture
async def world(db):
    await load_missing_years(db, CALENDAR_DIR)
    admin = await make_user(db, 1, Role.ADMIN)
    accountant = await make_user(db, 2)
    stranger = await make_user(db, 3)
    helper = await make_user(db, 4, Role.ASSISTANT)
    client_user = await make_user(db, 5, Role.CLIENT)
    company = await make_company(db, accountant, 1)
    await link_client(db, company, client_user)
    return locals()


def body(company, **fields) -> dict:
    return {
        "company_id": company.id,
        "knd": "1165050",
        "number": "100",
        "doc_date": "2026-11-27",
    } | fields


async def create(client, user, data) -> dict:
    response = await client.post("/api/demands", json=data, headers=auth(user))
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(
    ("sent", "workdays", "receipt", "response"),
    [
        (date(2026, 11, 27), 5, date(2026, 12, 7), date(2026, 12, 14)),
        (date(2026, 8, 21), 10, date(2026, 8, 31), date(2026, 9, 14)),
        # 4 ноября — нерабочий день
        (date(2026, 10, 30), 8, date(2026, 11, 10), date(2026, 11, 20)),
        # новогодние выходные
        (date(2026, 12, 25), 5, date(2027, 1, 13), date(2027, 1, 20)),
    ],
)
async def test_golden_dates(db, world, sent, workdays, receipt, response):
    calendar = await load_calendar(db)

    got = add_workdays(calendar, sent, get_book().receipt.workdays)

    assert (got, add_workdays(calendar, got, workdays)) == (receipt, response)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Форма по КНД 1165050 Требование № 7 о представлении пояснений 02.03.2026 "
            # номер сноски прилипает к числу дней
            "В течение 54 рабочих дней со дня получения настоящего Требования",
            ("1165050", "7", date(2026, 3, 2), 5, None, None),
        ),
        (
            "Форма по КНД 1165013 Требование № 18-1/2 о представлении документов 06.05.2026 "
            "необходимо представить в течение пяти рабочих дней со дня получения",
            ("1165013", "18-1/2", date(2026, 5, 6), 5, None, None),
        ),
        (
            "Форма по КНД 1160001 Требование № 55 об уплате задолженности по состоянию на "
            "«30» октября 2026 г. Сумма 1234,56 Статус 01 "
            "если в срок до «20» ноября 2026 года настоящее требование",
            ("1160001", "55", date(2026, 10, 30), None, date(2026, 11, 20), 123_456),
        ),
        (
            "Форма по КНД 1165009 Уведомление № 10/1 о вызове 16.10.2026 (адрес и номер "
            "кабинета) 05.11.2026 в 11.00 (дата и время или приемные дни и часы)",
            ("1165009", "10/1", date(2026, 10, 16), None, date(2026, 11, 5), None),
        ),
    ],
)
def test_reads_requisites(text, expected):
    found = read(text)

    assert (
        found.knd,
        found.number,
        found.doc_date,
        found.response_workdays,
        found.response_date,
        found.amount_kopecks,
    ) == expected


def test_visit_with_reception_hours_only_needs_a_date():
    found = read(
        "КНД 1165009 (адрес и номер кабинета) пн-чт с 09.00 до 18.00; "
        "(дата и время или приемные дни и часы)"
    )

    assert (found.response_date, found.note) == (None, "Приём: пн-чт с 09.00 до 18.00")


def test_pdf_text_and_unreadable_file():
    text = pdf_text(pdf("Форма по КНД 1165050", "Требование № 9"))

    assert read(text).knd == "1165050" and read(text).number == "9"
    assert pdf_text(b"%PDF-1.7 broken") == ""


async def test_recognize_finds_own_company(client, world):
    company = world["company"]
    data = pdf(
        "Форма по КНД 1165050",
        f"ИНН/КПП {company.inn}/000001001",
        "Требование № 5 от 27.11.2026",
        "В течение 5 рабочих дней со дня получения настоящего Требования",
    )

    for name, found in (("accountant", company.id), ("stranger", None)):
        response = await client.post(
            "/api/demands/recognize", content=data, headers=auth(world[name])
        )
        got = response.json()
        assert (got["readable"], got["company_id"], got["inn"]) == (True, found, company.inn)
    scan = await client.post(
        "/api/demands/recognize", content=b"\xff\xd8\xff photo", headers=auth(world["admin"])
    )
    assert scan.json()["readable"] is False


async def test_creates_two_calendar_tasks(client, db, world):
    company = world["company"]

    got = await create(client, world["accountant"], body(company, note="ответить письмом"))

    assert (got["receipt_date"], got["response_date"]) == ("2026-12-07", "2026-12-14")
    assert got["closed"] is False and got["receipt"]["status"] == "planned"
    listed = await client.get(
        "/api/tasks",
        params={"from": "2026-12-01", "to": "2026-12-31", "company_id": company.id},
        headers=auth(world["accountant"]),
    )
    rows = listed.json()["items"]
    assert [(row["due_date"], row["demand_id"], row["title"]) for row in rows] == [
        ("2026-12-07", got["id"], "Подписать квитанцию о приёме: требование о пояснениях № 100"),
        ("2026-12-14", got["id"], "Представить пояснения: требование о пояснениях № 100"),
    ]
    # клиенту требования не видны
    hidden = await client.get("/api/tasks", headers=auth(world["client_user"]))
    assert hidden.json()["items"] == []


async def test_payment_demand_keeps_date_and_amount(client, db, world):
    got = await create(
        client,
        world["admin"],
        body(
            world["company"],
            knd="1160001",
            doc_date="2026-10-30",
            response_date="2026-11-20",
            amount_kopecks=123_456,
            receipt_done=True,
        ),
    )

    assert (got["receipt"]["status"], got["response_date"]) == ("done", "2026-11-20")
    task = await db.get(Task, got["response"]["task_id"])
    assert (task.kind, task.amount_kopecks) == ("payment", 123_456)


async def test_visit_without_date_is_rejected(client, world):
    response = await client.post(
        "/api/demands",
        json=body(world["company"], knd="1165009"),
        headers=auth(world["accountant"]),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Укажите: дата явки"


async def test_duplicate_is_rejected(client, world):
    await create(client, world["accountant"], body(world["company"]))

    again = await client.post(
        "/api/demands", json=body(world["company"]), headers=auth(world["accountant"])
    )

    assert again.status_code == 409


async def test_change_moves_tasks_and_restarts_reminders(client, db, world):
    got = await create(client, world["accountant"], body(world["company"]))
    task_id = got["response"]["task_id"]
    db.add(
        Notification(
            user_id=world["accountant"].id,
            task_id=task_id,
            type="demand",
            scheduled_for=date(2026, 12, 9),
        )
    )
    await db.commit()

    changed = await client.put(
        f"/api/demands/{got['id']}",
        json=body(world["company"], receipt_date="2026-12-01"),
        headers=auth(world["accountant"]),
    )

    assert changed.json()["response_date"] == "2026-12-08"
    task = await db.get(Task, task_id, populate_existing=True)
    assert task.due_date == date(2026, 12, 8)
    assert (await db.scalars(select(Notification))).all() == []


async def test_task_is_changed_only_through_demand(client, db, world):
    got = await create(client, world["accountant"], body(world["company"]))
    url = f"/api/tasks/{got['response']['task_id']}"
    headers = auth(world["accountant"])

    for change in ({"due_date": "2027-01-01"}, {"client_visible": True}):
        assert (await client.patch(url, json=change, headers=headers)).status_code == 422
    assert (await client.delete(url, headers=headers)).status_code == 422
    done = await client.patch(url, json={"status": "done", "comment": "ушло"}, headers=headers)
    assert done.status_code == 200
    closed = await client.get(f"/api/demands/{got['id']}", headers=headers)
    assert closed.json()["closed"] is True

    assert (await client.delete(f"/api/demands/{got['id']}", headers=headers)).status_code == 204
    assert (await db.scalars(select(Task.id).where(Task.demand_id.is_not(None)))).all() == []


@pytest.mark.parametrize(
    ("name", "view", "change"),
    [
        ("admin", 200, 201),
        ("accountant", 200, 201),
        ("helper", 200, 403),
        ("stranger", 404, 404),
        ("client_user", 403, 403),
    ],
)
async def test_access(client, world, name, view, change):
    got = await create(client, world["accountant"], body(world["company"]))
    url = f"/api/demands/{got['id']}"
    headers = auth(world[name])

    assert (await client.get(url, headers=headers)).status_code == view
    listed = await client.get("/api/demands", headers=headers)
    assert (listed.status_code == 200 and len(listed.json()) == 1) == (view == 200)
    created = await client.post(
        "/api/demands", json=body(world["company"], number="101"), headers=headers
    )
    assert created.status_code == change
    upload = await client.post(
        f"{url}/file", content=pdf("x"), headers=headers | {"X-Filename": "a.pdf"}
    )
    assert upload.status_code == (200 if change == 201 else change)


async def test_file_is_stored_and_returned(client, db, world):
    got = await create(client, world["accountant"], body(world["company"]))
    url = f"/api/demands/{got['id']}/file"
    headers = auth(world["accountant"])
    data = pdf("Требование")

    bad = await client.post(url, content=b"text", headers=headers)
    good = await client.post(url, content=data, headers=headers | {"X-Filename": quote("Треб.pdf")})

    assert bad.status_code == 415
    assert (good.json()["filename"], good.json()["content_type"]) == ("Треб.pdf", "application/pdf")
    assert (await client.get(url, headers=auth(world["helper"]))).content == data
    assert (await client.get(url, headers=auth(world["stranger"]))).status_code == 404
    assert (await db.scalar(select(Demand.filename))) == "Треб.pdf"


async def test_reminders_use_own_workday_thresholds(client, db, world):
    got = await create(client, world["accountant"], body(world["company"]))
    settings = get_store().get()
    # четверг 10.12: до квитанции (07.12) срок прошёл, до ответа (14.12) 2 рабочих дня
    morning = datetime(2026, 12, 10, 7, 0, tzinfo=UTC)

    await plan(db, settings, morning)
    await plan(db, settings, morning)

    rows = (await db.scalars(select(Notification).where(Notification.type == "demand"))).all()
    assert {row.user_id for row in rows} == {world["accountant"].id, world["admin"].id}
    # ближайший из порогов 5, 3, 1, 0 — «за 3»
    assert {(row.task_id, row.scheduled_for) for row in rows} == {
        (got["response"]["task_id"], date(2026, 12, 11))
    }

    async with FakeTelegram() as telegram:
        bot = create_bot(get_config(), None, telegram.api("127.0.0.1"))
        try:
            await deliver(db, bot, settings, morning, pause=0)
        finally:
            await bot.session.close()
    texts = [text for _, text in telegram.sent if "📄" in text]
    assert len(texts) == 2
    assert "Представить пояснения" in texts[0] and "осталось рабочих дней: 2" in texts[0]


async def test_admin_reminders_can_be_switched_off(client, db, world):
    await create(client, world["accountant"], body(world["company"]))
    get_store().update({"notifications": {"demand_notify_admin": False}})

    await plan(db, get_store().get(), datetime(2026, 12, 3, 7, 0, tzinfo=UTC))

    rows = (await db.scalars(select(Notification).where(Notification.type == "demand"))).all()
    # квитанция 07.12 — за 2 рабочих дня; ответ 14.12 ещё далеко
    assert [(row.user_id, row.scheduled_for) for row in rows] == [
        (world["accountant"].id, date(2026, 12, 5))
    ]
