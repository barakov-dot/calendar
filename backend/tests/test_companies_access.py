"""Изоляция: кто какие компании видит и меняет."""

from datetime import date

import pytest
from sqlalchemy import select

from app.core.permissions import get_accessible_company_ids
from app.core.settings_store import get_store
from app.main import app
from app.models import Company, CompanyMember, Patent, Role
from app.services.inn import with_check_digits
from tests.factories import auth, link_client, make_company, make_user

pytestmark = pytest.mark.usefixtures("secrets")


@pytest.fixture
async def world(db):
    get_store().update({"telegram": {"bot_username": "some_bot"}})
    admin = await make_user(db, 1, Role.ADMIN)
    first = await make_user(db, 2)
    second = await make_user(db, 3)
    client_a = await make_user(db, 4, Role.CLIENT)
    client_b = await make_user(db, 5, Role.CLIENT)
    own = await make_company(db, first, 1, notes="секретная заметка")
    other = await make_company(db, second, 2, entity_type="ip", inn=with_check_digits("0000000002"))
    archived = await make_company(db, first, 3, is_archived=True)
    await link_client(db, own, client_a)
    await link_client(db, other, client_b, can_mark_paid=True)
    await link_client(db, archived, client_a)
    patent = Patent(company_id=other.id, date_start=date(2026, 1, 1), date_end=date(2026, 2, 1))
    db.add(patent)
    await db.commit()
    return locals()


async def test_accessible_company_ids(db, world):
    own, other, archived = world["own"], world["other"], world["archived"]
    expected = {
        "admin": {own.id, other.id, archived.id},
        "first": {own.id, archived.id},
        "second": {other.id},
        "client_a": {own.id},  # архивная клиенту не видна
        "client_b": {other.id},
    }
    for name, ids in expected.items():
        assert await get_accessible_company_ids(db, world[name]) == ids, name


# Все эндпоинты одной компании. Новый эндпоинт без строки здесь ломает проверку полноты ниже.
COMPANY_ENDPOINTS = [
    ("GET", "/api/companies/{company_id}", None),
    ("PATCH", "/api/companies/{company_id}", {"company": {"name": "Чужое"}}),
    ("DELETE", "/api/companies/{company_id}", None),
    ("POST", "/api/companies/{company_id}/refresh-dadata", None),
    ("GET", "/api/companies/{company_id}/patents", None),
    (
        "POST",
        "/api/companies/{company_id}/patents",
        {"date_start": "2026-01-01", "date_end": "2026-02-01"},
    ),
    (
        "PATCH",
        "/api/companies/{company_id}/patents/{patent_id}",
        {"date_start": "2026-01-01", "date_end": "2026-02-01"},
    ),
    ("DELETE", "/api/companies/{company_id}/patents/{patent_id}", None),
    ("PATCH", "/api/companies/{company_id}/members/{user_id}", {"can_mark_paid": False}),
    ("DELETE", "/api/companies/{company_id}/members/{user_id}", None),
    ("GET", "/api/companies/{company_id}/invites", None),
    ("POST", "/api/companies/{company_id}/invites", {}),
    ("DELETE", "/api/companies/{company_id}/invites/{invite_id}", None),
]


def test_every_company_endpoint_is_covered():
    declared = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/companies/{")
        for method in operations
    }

    assert declared == {(method, path) for method, path, _ in COMPANY_ENDPOINTS}


async def snapshot(db) -> list:
    result = []
    for model in (Company, CompanyMember, Patent):
        rows = await db.execute(select(model.__table__).order_by(*model.__table__.primary_key))
        result.append([tuple(row) for row in rows])
    return result


@pytest.mark.parametrize(("method", "path", "body"), COMPANY_ENDPOINTS)
async def test_foreign_company_is_not_available(client, db, world, method, path, body):
    url = path.format(
        company_id=world["other"].id,
        patent_id=world["patent"].id,
        user_id=world["client_b"].id,
        invite_id=1,
    )
    strangers = [auth(world["first"]), auth(world["client_a"])]
    own_client = auth(world["client_b"])
    before = await snapshot(db)

    assert (await client.request(method, url, json=body)).status_code == 401
    for headers in strangers:
        response = await client.request(method, url, json=body, headers=headers)
        read_by_client = method == "GET" and path.endswith("{company_id}")
        expected = {404} if read_by_client else {403, 404}
        assert response.status_code in expected
    if not (method == "GET" and path.endswith("{company_id}")):
        # клиент своей компании только смотрит
        response = await client.request(method, url, json=body, headers=own_client)
        assert response.status_code == 403

    assert await snapshot(db) == before


@pytest.mark.parametrize(
    "path",
    ["/patents/{patent_id}", "/members/{user_id}", "/invites/{invite_id}"],
)
async def test_nested_object_of_foreign_company_via_own(client, db, world, path):
    invite = await client.post(
        f"/api/companies/{world['other'].id}/invites", json={}, headers=auth(world["second"])
    )
    url = f"/api/companies/{world['own'].id}" + path.format(
        patent_id=world["patent"].id, user_id=world["client_b"].id, invite_id=invite.json()["id"]
    )
    before = await snapshot(db)

    response = await client.delete(url, headers=auth(world["first"]))

    assert response.status_code == 404
    assert await snapshot(db) == before


@pytest.mark.parametrize(
    ("user", "visible"),
    [("admin", {"own", "other"}), ("first", {"own"}), ("second", {"other"})],
)
async def test_list_is_limited(client, world, user, visible):
    response = await client.get("/api/companies", headers=auth(world[user]))

    assert {item["id"] for item in response.json()} == {world[name].id for name in visible}


@pytest.mark.parametrize("url", ["/api/companies", "/api/companies?archived=true"])
async def test_client_sees_only_public_fields(client, world, url):
    headers = auth(world["client_a"])

    listed = await client.get(url, headers=headers)
    single = await client.get(f"/api/companies/{world['own'].id}", headers=headers)

    public = {"id", "inn", "name", "short_name"}
    assert set(single.json()) == public
    assert all(set(item) == public for item in listed.json())
    assert "секретная" not in listed.text + single.text
    expected = [] if "archived" in url else [world["own"].id]
    assert [item["id"] for item in listed.json()] == expected


async def test_search_does_not_widen_access(client, world):
    response = await client.get(
        "/api/companies", params={"q": "Компания"}, headers=auth(world["first"])
    )

    assert [item["id"] for item in response.json()] == [world["own"].id]


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("GET", "/api/companies/suggest?q=Ромашка", None),
        ("POST", "/api/companies", {"company": {}}),
    ],
)
async def test_client_cannot_create(client, world, method, url, body):
    response = await client.request(method, url, json=body, headers=auth(world["client_a"]))

    assert response.status_code == 403


@pytest.mark.parametrize("user", ["first", "client_a"])
async def test_reassign_and_staff_are_admin_only(client, world, user):
    headers = auth(world[user])
    url = f"/api/admin/companies/{world['own'].id}/reassign"
    body = {"accountant_id": world["second"].id}

    assert (await client.post(url, json=body, headers=headers)).status_code == 403
    assert (await client.get("/api/staff", headers=headers)).status_code == 403
