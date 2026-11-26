import pytest
from sqlalchemy import select

from app.api import companies as api
from app.core.settings_store import get_store
from app.models import AuditLog, Company, CompanyMember, InviteKind, Role
from app.services import dadata, invites
from app.services.dadata.client import parse_party
from app.services.inn import is_valid_inn, with_check_digits
from tests.factories import auth, link_client, make_company, make_user

pytestmark = pytest.mark.usefixtures("secrets")

OOO_INN = with_check_digits("000000007")
IP_INN = with_check_digits("0000000007")
OOO = {"inn": OOO_INN, "name": "ООО «Ромашка»", "entity_type": "ooo", "main_regime": "osno"}
IP = {"inn": IP_INN, "name": "ИП Иванов", "entity_type": "ip", "main_regime": "usn6"}
PATENT = {"number": "1", "date_start": "2026-01-01", "date_end": "2026-12-31"}


@pytest.fixture
async def staff(db):
    get_store().update({"telegram": {"bot_username": "some_bot"}})
    admin = await make_user(db, 1, Role.ADMIN)
    accountant = await make_user(db, 2, first_name="Борис")
    return admin, accountant


async def actions(db) -> list[str]:
    return list(await db.scalars(select(AuditLog.action).order_by(AuditLog.id)))


@pytest.mark.parametrize(
    ("inn", "valid"),
    [
        ("7707083893", True),
        ("500100732259", True),
        ("7707083894", False),
        ("500100732258", False),
        ("77070838", False),
        ("770708389a", False),
        ("７７０７０８３８９３", False),
    ],
)
def test_inn_check_digits(inn, valid):
    assert is_valid_inn(inn) is valid


async def test_accountant_creates_company_for_self(client, db, staff):
    admin, accountant = staff

    response = await client.post(
        "/api/companies",
        json={"company": OOO, "accountant_id": admin.id},
        headers=auth(accountant),
    )

    body = response.json()
    assert response.status_code == 201, body
    assert (body["accountant_id"], body["accountant_name"]) == (accountant.id, "Борис")
    # значения по умолчанию для ООО на ОСНО
    assert body["nds_payer"] is True
    assert body["profit_advances_mode"] == "monthly_by_quarter"
    assert body["region_code"] == "00"
    assert await actions(db) == ["company.create"]


async def test_admin_chooses_accountant(client, db, staff):
    admin, accountant = staff
    client_user = await make_user(db, 3, Role.CLIENT)
    headers = auth(admin)

    bad = await client.post(
        "/api/companies", json={"company": OOO, "accountant_id": client_user.id}, headers=headers
    )
    good = await client.post(
        "/api/companies", json={"company": OOO, "accountant_id": accountant.id}, headers=headers
    )

    assert bad.status_code == 422
    assert good.json()["accountant_id"] == accountant.id


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"inn": "1234567890"}, "ИНН"),
        ({"inn": IP_INN}, "10 цифр"),
        ({"name": ""}, "name"),
        ({"main_regime": "envd"}, "main_regime"),
        ({"kpp": "12"}, "kpp"),
        ({"accountant_id": 1}, "accountant_id"),
        ({"is_archived": True}, "is_archived"),
    ],
)
async def test_invalid_company_is_rejected(client, db, staff, change, message):
    response = await client.post(
        "/api/companies", json={"company": OOO | change}, headers=auth(staff[1])
    )

    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert (await db.scalars(select(Company))).all() == []


async def test_incompatible_flags_are_reset(client, staff):
    headers = auth(staff[1])
    ip = IP | {
        "main_regime": "ausn_income",
        "nds_payer": True,
        "has_property_avg": True,
        "has_property_advances": True,
        "ausn_ndfl_tasks": False,
        "has_transport_tax": True,
        "kpp": "770701001",
        "profit_advances_mode": "monthly_actual",
    }

    body = (await client.post("/api/companies", json={"company": ip}, headers=headers)).json()

    assert body["nds_payer"] is False
    assert body["has_property_avg"] is False
    assert body["has_property_advances"] is False
    assert body["has_transport_tax"] is True  # транспорт бывает и у ИП
    assert body["ausn_ndfl_tasks"] is False
    assert (body["kpp"], body["profit_advances_mode"]) == ("", None)


async def test_duplicate_inn(client, db, staff):
    await make_company(db, staff[0], inn=OOO_INN, is_archived=True)

    response = await client.post("/api/companies", json={"company": OOO}, headers=auth(staff[1]))

    assert response.status_code == 409
    assert "в архиве" in response.json()["detail"]


async def test_patents(client, db, staff):
    headers = auth(staff[1])
    created = await client.post(
        "/api/companies", json={"company": IP, "patents": [PATENT]}, headers=headers
    )
    company_id = created.json()["id"]
    url = f"/api/companies/{company_id}/patents"
    assert len(created.json()["patents"]) == 1

    added = await client.post(
        url, json=PATENT | {"number": "2", "cost_kopecks": 100_50}, headers=headers
    )
    assert added.json()["cost_kopecks"] == 10050
    patent_url = f"{url}/{added.json()['id']}"
    edited = await client.patch(patent_url, json=PATENT | {"number": "3"}, headers=headers)
    assert edited.json()["number"] == "3"

    # ИП с патентами нельзя превратить в ООО
    response = await client.patch(
        f"/api/companies/{company_id}",
        json={"company": {"entity_type": "ooo", "inn": OOO_INN}},
        headers=headers,
    )
    assert "патенты" in response.json()["detail"]

    assert (await client.delete(patent_url, headers=headers)).status_code == 204
    assert len((await client.get(url, headers=headers)).json()) == 1
    assert await actions(db) == [
        "company.create",
        "patent.create",
        "patent.update",
        "patent.delete",
    ]


@pytest.mark.parametrize(
    "patent",
    [
        PATENT | {"date_end": "2025-12-31"},
        PATENT | {"date_end": "2027-01-31"},
        PATENT | {"cost_kopecks": -1},
        PATENT | {"cost_kopecks": 1.5},
    ],
)
async def test_invalid_patent(client, db, staff, patent):
    company = await make_company(db, staff[1], entity_type="ip", inn=IP_INN)

    response = await client.post(
        f"/api/companies/{company.id}/patents", json=patent, headers=auth(staff[1])
    )

    assert response.status_code == 422


async def test_ooo_has_no_patents(client, db, staff):
    headers = auth(staff[1])
    response = await client.post(
        "/api/companies", json={"company": OOO, "patents": [PATENT]}, headers=headers
    )
    assert response.status_code == 422
    company = await make_company(db, staff[1])
    response = await client.post(
        f"/api/companies/{company.id}/patents", json=PATENT, headers=headers
    )
    assert response.status_code == 422


async def test_edit_archive_restore_and_journal(client, db, staff):
    accountant = staff[1]
    company = await make_company(db, accountant)
    url = f"/api/companies/{company.id}"
    headers = auth(accountant)

    edited = await client.patch(
        url, json={"company": {"has_employees": True, "notes": "тайна"}}, headers=headers
    )
    assert edited.json()["has_employees"] is True
    assert (await client.delete(url, headers=headers)).status_code == 204
    assert (await client.get("/api/companies", headers=headers)).json() == []
    archived = await client.get("/api/companies?archived=true", headers=headers)
    assert [item["id"] for item in archived.json()] == [company.id]
    restored = await client.patch(url, json={"is_archived": False}, headers=headers)
    assert restored.json()["is_archived"] is False

    first = (await db.scalars(select(AuditLog).order_by(AuditLog.id))).first()
    assert first.payload["changes"] == {"has_employees": True, "notes": None}


async def test_list_badges_and_search(client, db, staff):
    accountant = staff[1]
    company = await make_company(db, accountant, 1, short_name="Ромашка")
    await make_company(db, accountant, 2, name="Лютик 100%")
    blocked = await make_user(db, 3, Role.CLIENT, bot_blocked=True)
    await link_client(db, company, blocked)
    headers = auth(accountant)

    async def find(q: str) -> list[dict]:
        return (await client.get("/api/companies", params={"q": q}, headers=headers)).json()

    [item] = await find("ромаш")
    assert (item["members_count"], item["has_blocked_member"]) == (1, True)
    assert item["accountant_name"] == "Борис"
    assert len(await find(company.inn[:9])) == 1
    assert [i["name"] for i in await find("100%")] == ["Лютик 100%"]
    assert await find("%") == await find("100%")  # знак процента не подстановка


async def test_reassign_revokes_open_invites(client, db, staff):
    admin, accountant = staff
    second = await make_user(db, 3)
    company = await make_company(db, accountant)
    await client.post(f"/api/companies/{company.id}/invites", json={}, headers=auth(admin))

    response = await client.post(
        f"/api/admin/companies/{company.id}/reassign",
        json={"accountant_id": second.id},
        headers=auth(admin),
    )

    assert response.json()["accountant_id"] == second.id
    url = f"/api/companies/{company.id}"
    assert (await client.get(url, headers=auth(accountant))).status_code == 404
    assert (await client.get(f"{url}/invites", headers=auth(admin))).json() == []


async def test_client_invite_binds_company(client, db, staff):
    accountant = staff[1]
    company = await make_company(db, accountant)
    headers = auth(accountant)
    url = f"/api/companies/{company.id}/invites"
    admin = auth(staff[0])
    # приглашает только администратор
    assert (await client.post(url, json={}, headers=headers)).status_code == 403
    assert (await client.get(url, headers=headers)).status_code == 403

    first = (await client.post(url, json={"can_mark_paid": True}, headers=admin)).json()
    second = (await client.post(url, json={}, headers=admin)).json()
    assert len((await client.get(url, headers=admin)).json()) == 2
    # приглашения клиентов не смешиваются с приглашениями бухгалтеров
    assert (await client.get("/api/admin/invites", headers=auth(staff[0]))).json() == []

    for number, invite in ((10, first), (11, second)):
        token = invite["link"].split("start=inv_")[1]
        await invites.accept(db, token, invites.TelegramProfile(number, "Клиент"))

    detail = (await client.get(f"/api/companies/{company.id}", headers=headers)).json()
    flags = [
        (m["can_mark_paid"], m["is_primary"], m["receive_reminders"]) for m in detail["members"]
    ]
    assert flags == [(True, True, True), (False, False, True)]


async def test_client_in_several_companies(db, staff):
    companies = [await make_company(db, staff[1], number) for number in (1, 2)]
    profile = invites.TelegramProfile(10)

    for company in companies:
        invite = await invites.create(db, InviteKind.CLIENT, staff[1], company_id=company.id)
        await invites.accept(db, invite.token, profile)
    repeated = await invites.create(db, InviteKind.CLIENT, staff[1], company_id=companies[0].id)
    with pytest.raises(invites.InviteError, match="уже подключены к этой компании"):
        await invites.accept(db, repeated.token, profile)

    assert len((await db.scalars(select(CompanyMember))).all()) == 2


async def test_invite_to_archived_company(client, db, staff):
    company = await make_company(db, staff[1], is_archived=True)
    response = await client.post(
        f"/api/companies/{company.id}/invites", json={}, headers=auth(staff[0])
    )
    assert response.status_code == 409
    invite = await invites.create(db, InviteKind.CLIENT, staff[1], company_id=company.id)
    token = invite.token
    with pytest.raises(invites.InviteError):
        await invites.accept(db, token, invites.TelegramProfile(10))


async def test_member_flags_are_personal_and_journaled(client, db, staff):
    accountant = staff[1]
    company = await make_company(db, accountant)
    one = await make_user(db, 10, Role.CLIENT)
    two = await make_user(db, 11, Role.CLIENT)
    await link_client(db, company, one)
    await link_client(db, company, two)
    url = f"/api/companies/{company.id}/members/{one.id}"
    headers = auth(accountant)

    response = await client.patch(url, json={"can_mark_paid": True}, headers=headers)
    await client.patch(url, json={"can_mark_paid": True}, headers=headers)

    assert {m["user_id"]: m["can_mark_paid"] for m in response.json()} == {
        one.id: True,
        two.id: False,
    }
    [entry] = (await db.scalars(select(AuditLog))).all()
    assert entry.payload == {
        "user_id": one.id,
        "changes": {"can_mark_paid": {"from": False, "to": True}},
    }
    assert (await client.delete(url, headers=headers)).status_code == 204
    assert (await client.get("/api/companies", headers=auth(one))).json() == []


def suggestion(inn: str = OOO_INN, **data) -> dict:
    return {
        "value": "ООО «Ромашка»",
        "data": {
            "inn": inn,
            "kpp": "000001001",
            "ogrn": "1000000000001",
            "type": "LEGAL",
            "name": {"full_with_opf": "ОБЩЕСТВО «РОМАШКА»", "short_with_opf": "ООО «Ромашка»"},
            "address": {"value": "г Тест", "data": {"region_kladr_id": "7700000000000"}},
            "okved": "62.01",
            "management": {"name": "Директор Тестовый"},
            "state": {"status": "ACTIVE"},
        }
        | data,
    }


@pytest.fixture
def dadata_found(monkeypatch):
    """Подменяет запрос к DaData, сохраняя кэш настоящего клиента."""
    get_store().update({"dadata": {"api_key": "key"}})
    results = [parse_party(suggestion())]
    dadata.client.cache.clear()

    async def fake(query, api_key, timeout_seconds, use_cache=True):
        for party in results:
            dadata.client.cache.put(f"party:{party.inn}", party)
        return results

    monkeypatch.setattr(api, "search", fake)
    yield results
    dadata.client.cache.clear()


async def test_suggest_create_and_refresh(client, db, staff, dadata_found):
    headers = auth(staff[1])

    found = (await client.get("/api/companies/suggest?q=Ромашка", headers=headers)).json()
    assert found["enabled"] is True
    [party] = found["suggestions"]
    assert (party["region_code"], party["director_name"]) == ("77", "Директор Тестовый")
    assert "raw" not in party

    fields = {k: v for k, v in party.items() if k != "status"}
    created = await client.post(
        "/api/companies",
        json={"company": fields | {"main_regime": "usn6", "notes": "моё"}},
        headers=headers,
    )
    assert created.status_code == 201, created.json()
    company = await db.get(Company, created.json()["id"])
    assert company.dadata_raw["data"]["inn"] == OOO_INN

    dadata_found[:] = [parse_party(suggestion(management={"name": "Новый Директор"}))]
    url = f"/api/companies/{company.id}/refresh-dadata"
    refreshed = (await client.post(url, headers=headers)).json()
    assert refreshed["director_name"] == "Новый Директор"
    assert (refreshed["main_regime"], refreshed["notes"]) == ("usn6", "моё")


async def test_dadata_disabled(client, db, staff):
    company = await make_company(db, staff[1])
    headers = auth(staff[1])
    get_store().update({"dadata": {"enabled": False, "api_key": "key"}})

    found = await client.get("/api/companies/suggest?q=Ромашка", headers=headers)
    refreshed = await client.post(f"/api/companies/{company.id}/refresh-dadata", headers=headers)

    assert found.json() == {"enabled": False, "suggestions": []}
    assert refreshed.status_code == 409


async def test_refresh_when_not_found(client, db, staff, dadata_found):
    company = await make_company(db, staff[1], 5)

    response = await client.post(
        f"/api/companies/{company.id}/refresh-dadata", headers=auth(staff[1])
    )

    assert response.status_code == 404
