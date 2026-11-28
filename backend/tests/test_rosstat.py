"""Формы Росстата. Ответы сервиса и организации в тестах выдуманы."""

import json
import ssl
from datetime import UTC, date, datetime

import httpx
import pytest
from sqlalchemy import select

from app.core.settings_store import get_store
from app.models import Role, RosstatForm, Task
from app.services import tasks
from app.services.rosstat import client as rosstat
from app.services.rosstat.parse import parse_date, parse_form
from app.services.rosstat.sync import due_since, run_due
from tests.factories import auth, link_client, make_company, make_user

pytestmark = pytest.mark.usefixtures("secrets")

NOW = datetime(2026, 11, 28, 6, 0, tzinfo=UTC)


def item(number, index="П-4", due="2026-12-15T00:00:00", period="за ноябрь 2026", **fields):
    return {
        "id": number,
        "index": index,
        "name": "Сведения о численности и заработной плате",
        "okud": "0606010",
        "form_period": "Месячная",
        "reported_period": period,
        "end_time": due,
        "comment": "",
    } | fields


class Site:
    """Поддельный websbor."""

    def __init__(self, forms=(), organizations=None, status=200):
        self.forms = list(forms)
        self.organizations = organizations
        self.status = status
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        if self.status != 200:
            return httpx.Response(self.status)
        if request.method == "POST":
            inn = json.loads(request.content)["inn"]
            default = [
                {"id": "branch", "inn": inn, "type": 2, "okpo": "2"},
                {"id": "head", "inn": inn, "type": 1, "okpo": "12345678"},
            ]
            return httpx.Response(
                200, json=default if self.organizations is None else self.organizations
            )
        return httpx.Response(200, json=self.forms)

    def client(self) -> rosstat.Client:
        return rosstat.Client(5, httpx.MockTransport(self))


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(tasks, "today", lambda: date(2026, 11, 28))


@pytest.fixture
async def world(db):
    admin = await make_user(db, 1, Role.ADMIN)
    accountant = await make_user(db, 2)
    stranger = await make_user(db, 3)
    helper = await make_user(db, 4, Role.ASSISTANT)
    client_user = await make_user(db, 5, Role.CLIENT)
    company = await make_company(db, accountant, 1)
    await link_client(db, company, client_user)
    return locals()


async def sync(db, site, now=NOW) -> int:
    async with site.client() as client:
        return await run_due(db, get_store().get(), now, client, pause=0)


async def forms_and_tasks(db):
    forms = (await db.scalars(select(RosstatForm).order_by(RosstatForm.id))).all()
    rows = (await db.scalars(select(Task).where(Task.rosstat_form_id.is_not(None)))).all()
    return forms, {task.rosstat_form_id: task for task in rows}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-12-15T00:00:00", date(2026, 12, 15)),
        ("15.12.2026", date(2026, 12, 15)),
        (1765746000000, date(2025, 12, 15)),
        ("после отчётного периода", None),
        ("2026-13-40", None),
        (None, None),
    ],
)
def test_deadline_formats(value, expected):
    assert parse_date(value) == expected


def test_form_without_date_keeps_the_text():
    form = parse_form(item(1, due="20 числа после отчетного периода"))

    assert (form.due_date, form.deadline) == (None, "20 числа после отчетного периода")
    assert parse_form({"id": 2}) is None


async def test_finds_head_office_and_creates_forms_with_tasks(db, world):
    site = Site([item(1), item(2, "МП (микро)", "когда-нибудь")])

    assert await sync(db, site) == 1

    assert site.requests[1] == ("GET", "/webstat/api/gs/organizations/head/forms")
    forms, found = await forms_and_tasks(db)
    assert [form.index for form in forms] == ["П-4", "МП (микро)"]
    [task] = found.values()
    assert (task.title, task.due_date, task.kind, task.client_visible) == (
        "Росстат: форма П-4 за ноябрь 2026",
        date(2026, 12, 15),
        "report",
        False,
    )
    company = world["company"]
    await db.refresh(company)
    assert (company.rosstat_okpo, company.rosstat_error) == ("12345678", "")


async def test_checks_once_a_day_after_the_set_time(db, world):
    site = Site([item(1)])
    await sync(db, site, datetime(2026, 11, 28, 1, 0, tzinfo=UTC))

    # тот же день: до следующего планового времени (03:00 МСК) повторов нет
    assert await sync(db, site, datetime(2026, 11, 28, 20, 0, tzinfo=UTC)) == 0
    company = world["company"]
    company.rosstat_checked_at = datetime(2026, 11, 27, 23, 0, tzinfo=UTC)
    await db.commit()
    assert await sync(db, site, datetime(2026, 11, 28, 0, 30, tzinfo=UTC)) == 1


def test_schedule_follows_setting():
    get_store().update({"rosstat": {"search_time": "23:30"}})

    moment = due_since(get_store().get(), datetime(2026, 11, 28, 6, 0, tzinfo=UTC))

    assert (moment.day, moment.hour, moment.minute) == (27, 23, 30)


async def test_repeat_keeps_status_and_removes_only_untouched_future(db, world):
    site = Site([item(1), item(2, "П-1"), item(3, "П-2", "2026-10-15")])
    await sync(db, site)
    forms, found = await forms_and_tasks(db)
    first = found[forms[0].id]
    first.status = "done"
    await db.commit()
    world["company"].rosstat_checked_at = None
    await db.commit()
    # П-4 перенесли, остальные пропали из перечня
    site.forms = [item(1, due="2026-12-17")]

    await sync(db, site)

    forms, found = await forms_and_tasks(db)
    assert [form.index for form in forms] == ["П-4", "П-2"]
    kept = found[forms[0].id]
    await db.refresh(kept)
    assert (kept.status, kept.due_date) == ("done", date(2026, 12, 17))


async def test_unavailable_site_leaves_everything_queued(db, world):
    with pytest.raises(rosstat.Unavailable):
        await sync(db, Site(status=503))

    company = world["company"]
    await db.refresh(company)
    assert company.rosstat_checked_at is None and "503" in company.rosstat_error


async def test_unknown_inn_is_recorded_and_not_retried_today(db, world):
    assert await sync(db, Site(organizations=[])) == 1

    company = world["company"]
    await db.refresh(company)
    assert "нет в статрегистре" in company.rosstat_error
    assert await sync(db, Site()) == 0


def test_certificate_error_is_explained():
    def broken(request):
        raise httpx.ConnectError("tls") from ssl.SSLCertVerificationError("self signed")

    async def run():
        async with rosstat.Client(5, httpx.MockTransport(broken)) as client:
            await client.organization("7707083893")

    import asyncio

    with pytest.raises(rosstat.Unavailable, match="сертификат Минцифры"):
        asyncio.run(run())


@pytest.mark.parametrize(
    ("name", "view", "refresh"),
    [
        ("admin", 200, 409),
        ("accountant", 200, 409),
        ("helper", 200, 403),
        ("stranger", 404, 404),
        ("client_user", 403, 403),
    ],
)
async def test_access(client, world, name, view, refresh):
    url = f"/api/companies/{world['company'].id}/rosstat"
    headers = auth(world[name])

    assert (await client.get(url, headers=headers)).status_code == view
    # поиск выключен в настройках, пока не загружен сертификат
    assert (await client.post(f"{url}/refresh", headers=headers)).status_code == refresh


async def test_company_tab_shows_forms_and_manual_refresh(client, db, world, monkeypatch):
    get_store().update({"rosstat": {"enabled": True}})
    site = Site([item(1)])
    real = rosstat.Client
    monkeypatch.setattr(rosstat, "Client", lambda timeout: real(timeout, httpx.MockTransport(site)))
    url = f"/api/companies/{world['company'].id}/rosstat"
    headers = auth(world["accountant"])

    response = await client.post(f"{url}/refresh", headers=headers)

    [form] = response.json()["forms"]
    assert (form["index"], form["status"], form["due_date"]) == ("П-4", "planned", "2026-12-15")
    task = f"/api/tasks/{form['task_id']}"
    assert (await client.delete(task, headers=headers)).status_code == 422
    done = await client.patch(task, json={"status": "done"}, headers=headers)
    assert done.status_code == 200


async def test_admin_certificate_and_queue(client, db, world):
    headers = auth(world["admin"])
    url = "/api/admin/rosstat"

    bad = await client.post(f"{url}/certificate", content=b"not a certificate", headers=headers)
    pem = ssl.create_default_context().get_ca_certs(binary_form=True)
    good = await client.post(f"{url}/certificate", content=pem[0], headers=headers)
    status = (await client.get(url, headers=headers)).json()

    assert (bad.status_code, good.status_code) == (422, 204)
    assert (status["has_certificate"], status["total"], status["checked"]) == (True, 1, 0)
    assert (await client.delete(f"{url}/certificate", headers=headers)).status_code == 204
    assert (await client.post(f"{url}/run", headers=headers)).status_code == 204
    other = auth(world["accountant"])
    assert (await client.get(url, headers=other)).status_code == 403
