"""Суммы из декларации по НДС. Все сведения в файлах выдуманы."""

from datetime import date

import pytest
from sqlalchemy import select

from app.models import AuditLog
from app.services.declarations.parser import MAX_BYTES, DeclarationError, parse
from tests.factories import auth, with_check_digits
from tests.test_payments import fresh, make_task, world  # noqa: F401

pytestmark = pytest.mark.usefixtures("secrets")

INN = with_check_digits(f"{1:09d}")  # ИНН первой компании из world


def declaration(
    inn=INN, total="611189", period="23", year="2026", correction="0", knd="1151001", extra=""
) -> bytes:
    text = f"""<?xml version="1.0" encoding="windows-1251"?>
<Файл ИдФайл="NO_NDS_test" ВерсФорм="5.12">
  <Документ КНД="{knd}" ДатаДок="20.10.2026" Период="{period}" ОтчетГод="{year}" \
НомКорр="{correction}">
    <СвНП><НПЮЛ НаимОрг="ООО &quot;Пример&quot;" ИННЮЛ="{inn}" КПП="000001001"/></СвНП>
    <Подписант ПрПодп="1"><ФИО Фамилия="Иванов" Имя="Иван"/></Подписант>
    <НДС>
      <СумУплНП ОКТМО="45000000" КБК="18210301000011000110" СумПУ_173.1="{total}"/>
      {extra}
    </НДС>
  </Документ>
</Файл>"""
    return text.encode("cp1251")


async def vat_tasks(db, company, period_key="2026-Q3", **second):
    return [
        await make_task(
            db,
            company,
            source="rule",
            rule_code="nds_payment",
            period_key=period_key,
            part=part,
            due_date=date(2026, 9 + part, 28),
            original_due_date=date(2026, 9 + part, 28),
            needs_amount=True,
            **(second if part == 2 else {}),
        )
        for part in (1, 2, 3)
    ]


async def send(client, user, data, action="preview"):
    return await client.post(f"/api/declarations/{action}", content=data, headers=auth(user))


def test_reads_period_inn_and_amount():
    found = parse(declaration(correction="2"))

    assert (found.inn, found.taxpayer) == (INN, 'ООО "Пример"')
    assert (found.period_key, found.correction) == ("2026-Q3", 2)
    assert (found.total_kopecks, found.warnings) == (61_118_900, ())


@pytest.mark.parametrize(
    ("code", "quarter"), [("21", 1), ("22", 2), ("23", 3), ("24", 4), ("56", 4)]
)
def test_period_codes(code, quarter):
    assert parse(declaration(period=code)).quarter == quarter


def test_sums_sections_and_warns_about_other_payments():
    extra = """<СумУплНП ОКТМО="46000000" СумПУ_173.1="100" СумПУ_173.5="50"/>
    <СумУплНА СумУплНА="700"/>"""

    found = parse(declaration(total="200", extra=extra))

    assert found.total_kopecks == 30_000
    first, second = found.warnings
    assert "50 ₽" in first and "налоговый агент" in second


def test_warns_when_nothing_to_pay():
    found = parse(declaration(total="0"))

    assert found.total_kopecks == 0
    assert "нулевыми" in found.warnings[0]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "пустой"),
        (b"%PDF-1.7", "не читается"),
        (b"<root/>", "не файл декларации"),
        (b"x" * (MAX_BYTES + 1), "больше 5 МБ"),
        (b'<!DOCTYPE a [<!ENTITY b "c">]><a>&b;</a>', "DTD"),
        (declaration(knd="1151006"), "по прибыли пока не"),
        (declaration(knd="1152017"), "только декларация по НДС"),
        (declaration(period="34"), "налоговый период"),
        (declaration(inn="123"), "ИНН"),
        (declaration(total="-5"), "целым числом"),
    ],
)
def test_rejects_unsuitable_files(data, message):
    with pytest.raises(DeclarationError, match=message):
        parse(data)


@pytest.mark.parametrize("name", ["admin", "accountant"])
async def test_preview_changes_nothing_and_apply_writes_thirds(client, db, world, name):  # noqa: F811
    parts = await vat_tasks(db, world["company"])

    preview = await send(client, world[name], declaration())

    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert (body["company_id"], body["year"], body["quarter"], body["total_kopecks"]) == (
        world["company"].id,
        2026,
        3,
        61_118_900,
    )
    assert body["warnings"] == []
    new = [part["new_kopecks"] for part in body["parts"]]
    assert sum(new) == 61_118_900 and max(new) - min(new) <= 2
    assert [(await fresh(db, task)).amount_kopecks for task in parts] == [None, None, None]

    applied = await send(client, world[name], declaration(), "apply")

    assert applied.status_code == 200, applied.text
    assert [part["current_kopecks"] for part in applied.json()["parts"]] == [None, None, None]
    assert [(await fresh(db, task)).amount_kopecks for task in parts] == new
    record = await db.scalar(select(AuditLog).where(AuditLog.action == "task.nds_amount"))
    assert record.payload["declaration_correction"] == 0


@pytest.mark.parametrize(
    ("second", "reason"),
    [
        ({"status": "paid", "amount_kopecks": 5}, "уже оплачен"),
        ({"amount_overridden": True, "amount_kopecks": 5}, "сумма введена вручную"),
    ],
)
async def test_paid_and_manual_parts_stay(client, db, world, second, reason):  # noqa: F811
    parts = await vat_tasks(db, world["company"], **second)

    response = await send(client, world["accountant"], declaration(), "apply")

    assert [part["kept"] for part in response.json()["parts"]] == ["", reason, ""]
    [warning] = response.json()["warnings"]
    assert "по декларации 611" in warning
    assert (await fresh(db, parts[1])).amount_kopecks == 5
    assert (await fresh(db, parts[0])).amount_kopecks is not None


@pytest.mark.parametrize(
    ("name", "status"),
    [("helper", 403), ("payer", 403), ("other_accountant", 422)],
)
async def test_who_may_not_load(client, db, world, name, status):  # noqa: F811
    parts = await vat_tasks(db, world["company"])

    for action in ("preview", "apply"):
        response = await send(client, world[name], declaration(), action)
        assert response.status_code == status

    assert (await fresh(db, parts[0])).amount_kopecks is None


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (declaration(inn=with_check_digits(f"{99:09d}")), "нет среди ваших"),
        (declaration(period="22"), "Платежей НДС за 2 квартал 2026 года нет"),
    ],
)
async def test_explains_why_there_is_nowhere_to_write(client, db, world, data, message):  # noqa: F811
    await vat_tasks(db, world["company"])

    response = await send(client, world["accountant"], data)

    assert response.status_code == 422
    assert message in response.json()["detail"]
