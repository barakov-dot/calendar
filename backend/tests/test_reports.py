"""Отчёт о выполненном за период."""

import io
from datetime import UTC, date, datetime, timedelta

import pytest
from openpyxl import load_workbook

from app.core.permissions import business_today
from app.models import Role, Task
from tests.factories import assign, auth, link_client, make_company, make_user

pytestmark = pytest.mark.usefixtures("secrets")


def moment(day: date, hour: int = 9) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


@pytest.fixture
async def world(db):
    admin = await make_user(db, 1, Role.ADMIN)
    helper = await make_user(db, 6, Role.ASSISTANT)
    first = await make_user(db, 2, first_name="Анна")
    second = await make_user(db, 3, first_name="Борис")
    payer = await make_user(db, 10, Role.CLIENT)
    company = await make_company(db, first, 1, short_name="=HYPERLINK(1)")
    other = await make_company(db, second, 2, short_name="ООО «Вторая»")
    await assign(db, company, helper)
    await link_client(db, company, payer)
    today = business_today()

    def task(owner, due_ago, status="planned", marked_ago=None, **fields):
        due = today - timedelta(days=due_ago)
        values = {
            "company_id": owner.id,
            "source": "custom",
            "kind": "payment",
            "title": "Налог",
            "due_date": due,
            "original_due_date": due,
            "status": status,
        } | fields
        if marked_ago is not None:
            values["status_changed_at"] = moment(today - timedelta(days=marked_ago))
            values["status_changed_by"] = first.id
            values.setdefault("status_changed_by_role", "accountant")
        return Task(**values)

    db.add_all(
        [
            task(company, 10, "paid", 12, amount_kopecks=100_00, title="Вовремя"),
            task(company, 10, "paid", 7, amount_kopecks=50_50, title="Поздно"),
            task(company, 8, "not_required", 8, title="Не нужно"),
            task(company, 5, title="Пропущено"),
            task(company, 0, title="Сегодня ещё не поздно"),
            task(company, 9, "not_required", 9, status_changed_by_role="system"),
            task(company, 200, "paid", 190, title="Давно"),
            task(other, 3, "done", 3, kind="report", title="Отчёт"),
        ]
    )
    await db.commit()
    params = {"from": str(today - timedelta(days=30)), "to": str(today)}
    return locals()


async def get(client, world, user="admin", extension="", **params):
    url = "/api/reports/completed" + (f".{extension}" if extension else "")
    return await client.get(url, params=world["params"] | params, headers=auth(world[user]))


async def test_summary(client, world):
    response = await get(client, world)

    body = response.json()
    assert response.status_code == 200, body
    assert body["tasks"] == 5
    assert body["summary"][0] == {
        "accountant": "Анна",
        "company": "=HYPERLINK(1)",
        "on_time": 1,
        "late": 1,
        "not_required": 1,
        "overdue": 1,
        "paid_kopecks": 15050,
    }
    assert body["summary"][1]["on_time"] == 1


@pytest.mark.parametrize(
    ("user", "companies"),
    [("admin", 2), ("helper", 1), ("first", 1), ("second", 1)],
)
async def test_limited_to_accessible(client, world, user, companies):
    assert len((await get(client, world, user)).json()["summary"]) == companies


async def test_filters_and_access(client, world):
    by_accountant = await get(client, world, accountant_id=world["second"].id)
    assert [row["accountant"] for row in by_accountant.json()["summary"]] == ["Борис"]
    foreign = await get(client, world, "first", company_id=world["other"].id)
    assert foreign.status_code == 404
    assert (await get(client, world, "first", accountant_id=world["second"].id)).json() == {
        "summary": [],
        "tasks": 0,
    }
    for extension in ("", "xlsx", "pdf"):
        assert (await get(client, world, "payer", extension)).status_code == 403
    backwards = await get(client, world, **{"from": "2027-01-02", "to": "2027-01-01"})
    assert backwards.status_code == 422


async def test_xlsx(client, world):
    response = await get(client, world, extension="xlsx")

    book = load_workbook(io.BytesIO(response.content))
    assert book.sheetnames == ["Итоги", "Задачи"]
    rows = list(book["Задачи"].iter_rows(min_row=5, values_only=True))
    late = next(row for row in rows if row[2] == "Поздно")
    assert (late[5], late[8], late[9]) == ("Оплачено", "С опозданием на 3 дн.", 50.5)
    # название компании не превратилось в формулу
    cell = book["Итоги"]["B5"]
    assert (cell.value, cell.data_type) == ("=HYPERLINK(1)", "s")
    assert response.headers["content-disposition"].endswith('.xlsx"')


@pytest.mark.parametrize("empty", [False, True])
async def test_pdf(client, world, empty):
    params = {"from": "2020-01-01", "to": "2020-02-01"} if empty else {}

    response = await get(client, world, extension="pdf", **params)

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")
    assert response.headers["content-type"] == "application/pdf"
