"""Требования инспекции. Все документы и сведения в тестах выдуманы."""

from datetime import UTC, date, datetime
from urllib.parse import quote

import pytest
from fpdf import FPDF
from sqlalchemy import select

from app.core.config import get_config
from app.core.settings_store import NotificationSettings, get_store
from app.models import CompanyMember, Demand, Notification, Role, Task, User
from app.services.calendar.workdays import load_calendar, load_missing_years
from app.services.demands import service
from app.services.demands.recognize import pdf_text, read
from app.services.demands.types import add_workdays, get_book
from app.services.notify import sender
from app.services.notify.planner import plan
from app.services.notify.sender import deliver
from app.services.reports import FONTS
from app.services.telegram.factory import create_bot
from tests.factories import assign, auth, link_client, make_company, make_user
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
    await assign(db, company, helper)
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
            "Форма по КНД 1165001 Решение № 7 о взыскании задолженности «17» ноября 2026 г. "
            "в связи с неисполнением требования об уплате задолженности от «9» октября "
            "2026 г. № 55 в размере 45,6 рублей. Сумма 45,6 Статус 01",
            ("1165001", "7", date(2026, 11, 17), None, None, 4560),
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


async def test_collection_decision_is_due_on_upload_day(client, db, world, monkeypatch):
    today = date(2026, 12, 1)
    monkeypatch.setattr(service, "business_today", lambda: today)
    data = body(world["company"], knd="1165001", doc_date="2026-11-24", amount_kopecks=36_40)

    got = await create(client, world["accountant"], data)

    assert (got["response_date"], got["response_set"], got["is_payment"]) == (
        "2026-12-01",
        True,
        True,
    )
    # квитанция — как у требований: 6-й рабочий день после получения
    assert got["receipt_date"] == "2026-12-02"
    task = await db.get(Task, got["response"]["task_id"])
    assert (task.kind, task.amount_kopecks, task.title) == (
        "payment",
        36_40,
        "Погасить задолженность: решение о взыскании № 100",
    )
    # позже при правке дата остаётся прежней
    monkeypatch.setattr(service, "business_today", lambda: date(2026, 12, 9))
    url = f"/api/demands/{got['id']}"
    changed = await client.put(
        url,
        json=data | {"response_date": got["response_date"], "note": "уточнение"},
        headers=auth(world["accountant"]),
    )
    assert changed.json()["response_date"] == "2026-12-01", changed.text


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

    url = f"/api/demands/{got['id']}"
    # удаляет только администратор
    assert (await client.delete(url, headers=headers)).status_code == 403
    assert (await client.delete(url, headers=auth(world["admin"]))).status_code == 204
    assert (await db.scalars(select(Task.id).where(Task.demand_id.is_not(None)))).all() == []


@pytest.mark.parametrize(
    ("name", "view", "change"),
    [
        ("admin", 200, 201),
        ("accountant", 200, 201),
        ("helper", 200, 403),
        ("stranger", 404, 404),
        ("client_user", 200, 403),
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
    # бухгалтеру и помощнику организации, администратору и клиенту
    assert {row.user_id for row in rows} == {
        world["accountant"].id,
        world["helper"].id,
        world["admin"].id,
        world["client_user"].id,
    }
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
    assert len(texts) == 4
    assert "Представить пояснения" in texts[0] and "осталось рабочих дней: 2" in texts[0]


async def test_admin_reminders_can_be_switched_off(client, db, world):
    await create(client, world["accountant"], body(world["company"]))
    get_store().update({"notifications": {"demand_notify_admin": False}})

    await plan(db, get_store().get(), datetime(2026, 12, 3, 7, 0, tzinfo=UTC))

    rows = (await db.scalars(select(Notification).where(Notification.type == "demand"))).all()
    # квитанция 07.12 — за 2 рабочих дня; ответ 14.12 ещё далеко
    assert sorted((row.user_id, row.scheduled_for) for row in rows) == [
        (world["accountant"].id, date(2026, 12, 5)),
        (world["helper"].id, date(2026, 12, 5)),
    ]


@pytest.mark.parametrize(
    ("switches", "expected"),
    [
        ({}, {"admin", "chief", "accountant", "helper"}),
        ({"demand_notify_admin": False}, {"chief", "accountant", "helper"}),
        (
            {"demand_notify_chief": False, "demand_notify_accountants": False},
            {"admin", "helper"},
        ),
        ({"demand_notify_assistants": False}, {"admin", "chief", "accountant"}),
        # общая галочка напоминаний помощникам на требования не влияет
        (
            {
                "demand_notify_admin": False,
                "demand_notify_chief": False,
                "demand_notify_accountants": False,
                "assistant_reminders": False,
            },
            {"helper"},
        ),
    ],
)
async def test_reminders_go_to_chosen_roles(client, db, world, switches, expected):
    world["chief"] = await make_user(db, 20, Role.CHIEF)
    await create(client, world["accountant"], body(world["company"]))
    get_store().update({"notifications": switches})
    settings = get_store().get()
    now = datetime(2026, 12, 3, 7, 0, tzinfo=UTC)

    await plan(db, settings, now)

    rows = (await db.scalars(select(Notification).where(Notification.type == "demand"))).all()
    names = ("admin", "chief", "accountant", "helper", "stranger")
    got = {name for name in names for row in rows if row.user_id == world[name].id}
    assert got == expected
    # перед отправкой права получателя проверяются ещё раз: каждое сообщение уходит
    for row in rows:
        user = await db.get(User, row.user_id)
        message = await sender._compose(db, settings, user, [row], now.date())
        assert message is not None, user.role


def test_old_admin_switch_also_covers_chief():
    old = NotificationSettings.model_validate({"demand_notify_admin": False})
    split = NotificationSettings.model_validate(
        {"demand_notify_admin": False, "demand_notify_chief": True}
    )

    assert (old.demand_notify_chief, split.demand_notify_chief) == (False, True)


async def test_client_sees_own_demand_without_note_and_tasks(client, db, world):
    got = await create(client, world["accountant"], body(world["company"], note="внутреннее"))
    headers = auth(world["client_user"])
    url = f"/api/demands/{got['id']}"
    await client.post(
        f"{url}/file", content=pdf("x"), headers=auth(world["accountant"]) | {"X-Filename": "a.pdf"}
    )
    other = await make_company(db, world["stranger"], 2)
    foreign = await create(client, world["admin"], body(other, number="200"))

    listed = (await client.get("/api/demands", headers=headers)).json()
    detail = (await client.get(url, headers=headers)).json()

    assert [item["id"] for item in listed] == [got["id"]]
    assert (detail["note"], detail["response"]["task_id"], detail["filename"]) == (
        "",
        None,
        "a.pdf",
    )
    assert (await client.get(f"{url}/file", headers=headers)).status_code == 200
    assert (await client.get(f"/api/demands/{foreign['id']}", headers=headers)).status_code == 404
    assert (await client.delete(url, headers=headers)).status_code == 403
    task = f"/api/tasks/{got['response']['task_id']}"
    assert (await client.get(task, headers=headers)).status_code == 404


async def test_company_filter(client, db, world):
    await create(client, world["accountant"], body(world["company"]))
    other = await make_company(db, world["accountant"], 2)
    got = await create(client, world["accountant"], body(other, number="200"))

    listed = await client.get(
        "/api/demands", params={"company_id": other.id}, headers=auth(world["accountant"])
    )

    assert [item["id"] for item in listed.json()] == [got["id"]]


@pytest.mark.parametrize(
    ("settings", "member", "expected"),
    [
        ({}, {}, True),
        ({"demand_notify_clients": False}, {}, False),
        ({}, {"receive_reminders": False}, False),
    ],
)
async def test_client_reminders_only_about_response(client, db, world, settings, member, expected):
    for row in await db.scalars(select(CompanyMember)):
        for name, value in member.items():
            setattr(row, name, value)
    await db.commit()
    got = await create(client, world["accountant"], body(world["company"]))
    if settings:
        get_store().update({"notifications": settings})

    # 03.12: и квитанция (07.12), и ответ уже в порогах 2 и 5 рабочих дней
    await plan(db, get_store().get(), datetime(2026, 12, 7, 7, 0, tzinfo=UTC))

    rows = await db.scalars(
        select(Notification.task_id).where(
            Notification.type == "demand", Notification.user_id == world["client_user"].id
        )
    )
    assert rows.all() == ([got["response"]["task_id"]] if expected else [])


async def share_setup(client, world):
    got = await create(client, world["accountant"], body(world["company"], note="внутреннее"))
    url = f"/api/demands/{got['id']}"
    await client.post(
        f"{url}/file",
        content=pdf("документ"),
        headers=auth(world["accountant"]) | {"X-Filename": "demand.pdf"},
    )
    return got, url


async def deliver_all(db) -> FakeTelegram:
    async with FakeTelegram() as telegram:
        bot = create_bot(get_config(), None, telegram.api("127.0.0.1"))
        try:
            await deliver(db, bot, get_store().get(), datetime.now(UTC), pause=0)
        finally:
            await bot.session.close()
    return telegram


async def test_recipients_are_linked_to_the_company(client, world):
    _, url = await share_setup(client, world)

    got = await client.get(f"{url}/recipients", headers=auth(world["accountant"]))

    assert {(item["user_id"], item["group"]) for item in got.json()} == {
        (world["client_user"].id, "client"),
        (world["accountant"].id, "accountant"),
        (world["helper"].id, "assistant"),
    }


async def test_share_sends_the_document_through_the_queue(client, db, world):
    _, url = await share_setup(client, world)
    chosen = [world["client_user"].id, world["helper"].id]
    headers = auth(world["accountant"])

    queued = await client.post(
        f"{url}/share", json={"user_ids": chosen, "comment": "Нужны документы"}, headers=headers
    )

    assert queued.status_code == 200, queued.text
    assert [item["status"] for item in queued.json() if item["user_id"] in chosen] == [
        "pending"
    ] * 2
    telegram = await deliver_all(db)
    assert sorted(chat for chat, _, _ in telegram.documents) == sorted(
        [world["client_user"].telegram_id, world["helper"].telegram_id]
    )
    assert {name for _, name, _ in telegram.documents} == {"demand.pdf"}
    after = await client.get(f"{url}/recipients", headers=headers)
    assert {item["status"] for item in after.json() if item["user_id"] in chosen} == {"sent"}


async def test_share_survives_change_of_dates(client, db, world):
    got, url = await share_setup(client, world)
    headers = auth(world["accountant"])
    await client.post(f"{url}/share", json={"user_ids": [world["helper"].id]}, headers=headers)

    await client.put(url, json=body(world["company"], receipt_date="2026-12-01"), headers=headers)

    assert (await db.scalar(select(Notification.type))) == "demand_share"


async def test_unlinked_recipient_gets_nothing(client, db, world):
    _, url = await share_setup(client, world)
    headers = auth(world["accountant"])

    foreign = await client.post(
        f"{url}/share", json={"user_ids": [world["stranger"].id]}, headers=headers
    )
    await client.post(f"{url}/share", json={"user_ids": [world["client_user"].id]}, headers=headers)
    for member in await db.scalars(select(CompanyMember)):
        await db.delete(member)
    await db.commit()

    assert foreign.status_code == 422
    # клиента отвязали, пока сообщение ждало отправки
    assert (await deliver_all(db)).documents == []


@pytest.mark.parametrize(
    ("name", "status"), [("helper", 403), ("client_user", 403), ("stranger", 404)]
)
async def test_who_may_not_share(client, world, name, status):
    _, url = await share_setup(client, world)

    response = await client.post(
        f"{url}/share", json={"user_ids": [world["accountant"].id]}, headers=auth(world[name])
    )

    assert response.status_code == status


@pytest.mark.parametrize(
    ("moment", "status"),
    [
        # квитанция 07.12; время московское (UTC+3)
        (datetime(2026, 12, 6, 20, 0, tzinfo=UTC), "planned"),
        (datetime(2026, 12, 7, 13, 59, tzinfo=UTC), "planned"),
        (datetime(2026, 12, 7, 14, 0, tzinfo=UTC), "done"),
        # воркер не работал в срок: отметка ставится при следующем запуске
        (datetime(2026, 12, 9, 6, 0, tzinfo=UTC), "done"),
    ],
)
async def test_receipt_is_signed_automatically_at_17(client, db, world, moment, status):
    got = await create(client, world["accountant"], body(world["company"]))

    await plan(db, get_store().get(), moment)

    receipt = await db.get(Task, got["receipt"]["task_id"], populate_existing=True)
    response = await db.get(Task, got["response"]["task_id"], populate_existing=True)
    assert (receipt.status, response.status) == (status, "planned")
    assert receipt.status_changed_by_role == ("system" if status == "done" else None)


async def test_returned_receipt_stays_and_new_date_reopens(client, db, world):
    got = await create(client, world["accountant"], body(world["company"]))
    headers = auth(world["accountant"])
    task_id = got["receipt"]["task_id"]
    await plan(db, get_store().get(), datetime(2026, 12, 7, 15, 0, tzinfo=UTC))

    # дату квитанции перенесли: автоматическая отметка снимается
    url = f"/api/demands/{got['id']}"
    moved = await client.put(
        url, json=body(world["company"], receipt_date="2026-12-10"), headers=headers
    )
    assert moved.json()["receipt"]["status"] == "planned"

    await plan(db, get_store().get(), datetime(2026, 12, 10, 15, 0, tzinfo=UTC))
    # человек вернул задачу в план: сервис больше не отмечает её сам
    await client.patch(f"/api/tasks/{task_id}", json={"status": "planned"}, headers=headers)
    await plan(db, get_store().get(), datetime(2026, 12, 11, 15, 0, tzinfo=UTC))

    task = await db.get(Task, task_id, populate_existing=True)
    assert task.status == "planned"
