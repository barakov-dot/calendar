"""Суммы из деклараций по НДС и прибыли. Все сведения и числа в файлах выдуманы."""

from datetime import date

import pytest
from sqlalchemy import select

from app.models import AuditLog, Task
from app.services import tasks
from app.services.declarations.parser import MAX_BYTES, DeclarationError, parse
from tests.factories import auth, with_check_digits
from tests.test_payments import fresh, make_task, world  # noqa: F401

pytestmark = pytest.mark.usefixtures("secrets")

INN = with_check_digits(f"{1:09d}")  # ИНН первой компании из world


def document(body, knd="1151001", inn=INN, period="23", year="2026", correction="0") -> bytes:
    text = f"""<?xml version="1.0" encoding="windows-1251"?>
<Файл ИдФайл="test" ВерсФорм="5.12">
  <Документ КНД="{knd}" ДатаДок="20.10.2026" Период="{period}" ОтчетГод="{year}" \
НомКорр="{correction}">
    <СвНП><НПЮЛ НаимОрг="ООО &quot;Пример&quot;" ИННЮЛ="{inn}" КПП="000001001"/></СвНП>
    <Подписант ПрПодп="1"><ФИО Фамилия="Иванов" Имя="Иван"/></Подписант>
    {body}
  </Документ>
</Файл>"""
    return text.encode("cp1251")


def nds(total="100000", extra="", **header) -> bytes:
    return document(f'<НДС><СумУплНП СумПУ_173.1="{total}"/>{extra}</НДС>', **header)


def due(federal, regional) -> str:
    return f'<НалПУАв><ФедБдж НалПУ="{federal}"/><СубБдж НалПУ="{regional}"/></НалПУАв>'


def monthly(federal, regional, quarter=None) -> str:
    def line(tag, values):
        first, second, third = values
        return f'<{tag} АвПлат1="{first}" АвПлат2="{second}" АвПлат3="{third}"/>'

    code = f' КвИсчислАв="{quarter}"' if quarter else ""
    return f"<НалПУМес{code}>{line('ФедБдж', federal)}{line('СубБдж', regional)}</НалПУМес>"


def profit(*blocks, period="31", **header) -> bytes:
    body = f"<Прибыль><НалПУ>{''.join(blocks)}</НалПУ></Прибыль>"
    return document(body, knd="1151006", period=period, **header)


def amounts(found, rule):
    return {item.period_key: item.amount_kopecks for item in found.items if item.rule_code == rule}


async def payment(db, company, rule, period_key, due_date, part=1, **fields):
    return await make_task(
        db,
        company,
        source="rule",
        rule_code=rule,
        period_key=period_key,
        part=part,
        due_date=due_date,
        original_due_date=due_date,
        needs_amount=True,
        **fields,
    )


async def vat_tasks(db, company, **second):
    return [
        await payment(
            db,
            company,
            "nds_payment",
            "2026-Q3",
            date(2026, 9 + part, 28),
            part,
            **(second if part == 2 else {}),
        )
        for part in (1, 2, 3)
    ]


async def send(client, user, data, action="preview"):
    return await client.post(f"/api/declarations/{action}", content=data, headers=auth(user))


def test_nds_is_split_and_rounded_up_to_rubles():
    found = parse(nds(correction="2"))

    assert (found.inn, found.taxpayer) == (INN, 'ООО "Пример"')
    assert (found.title, found.correction) == ("НДС за III квартал 2026", 2)
    assert [(item.period_key, item.part) for item in found.items] == [
        ("2026-Q3", 1),
        ("2026-Q3", 2),
        ("2026-Q3", 3),
    ]
    assert [item.amount_kopecks for item in found.items] == [33_334_00] * 3
    assert found.totals == (("К уплате за квартал", 100_000_00),)
    assert found.warnings == ()


@pytest.mark.parametrize(
    ("code", "quarter"), [("21", 1), ("22", 2), ("23", 3), ("24", 4), ("56", 4)]
)
def test_nds_period_codes(code, quarter):
    assert parse(nds(period=code)).items[0].period_key == f"2026-Q{quarter}"


def test_nds_sums_sections_and_warns_about_other_payments():
    extra = """<СумУплНП СумПУ_173.1="100" СумПУ_173.5="50"/><СумУплНА СумУплНА="700"/>"""

    found = parse(nds("200", extra))

    assert found.totals[0][1] == 30_000
    first, second = found.warnings
    assert "50 ₽" in first and "налоговый агент" in second


def test_nds_warns_when_nothing_to_pay():
    found = parse(nds("0"))

    assert found.totals[0][1] == 0
    assert "нулевыми" in found.warnings[0]


def test_profit_quarter_gives_surcharge_and_next_monthly_advances():
    found = parse(profit(due(100, 200), monthly((10, 10, 11), (20, 20, 20)), period="21"))

    assert found.title == "Налог на прибыль за I квартал 2026"
    assert amounts(found, "profit_advance") == {"2026-Q1": 300_00}
    # 91 ₽ за квартал — три раза по 31 ₽
    assert amounts(found, "profit_monthly") == {
        "2026-04": 31_00,
        "2026-05": 31_00,
        "2026-06": 31_00,
    }


def test_profit_reduction_means_nothing_to_pay():
    found = parse(profit(due(-100, -200), monthly((1, 1, 1), (2, 2, 2))))

    assert found.totals[0] == ("К уменьшению", 300_00)
    assert amounts(found, "profit_advance") == {"2026-Q2": 0}
    assert list(amounts(found, "profit_monthly")) == ["2026-07", "2026-08", "2026-09"]


def test_profit_nine_months_covers_next_year_first_quarter():
    blocks = (
        due(1, 2),
        monthly((100, 100, 100), (200, 200, 200), quarter="24"),
        monthly((10, 10, 10), (20, 20, 20), quarter="21"),
    )

    found = parse(profit(*blocks, period="33"))

    assert found.title == "Налог на прибыль за 9 месяцев 2026"
    assert amounts(found, "profit_monthly") == {
        "2026-10": 300_00,
        "2026-11": 300_00,
        "2026-12": 300_00,
        "2027-01": 30_00,
        "2027-02": 30_00,
        "2027-03": 30_00,
    }


@pytest.mark.parametrize(
    ("code", "rule", "key"),
    [
        ("34", "profit_year", "2026"),
        ("46", "profit_year", "2026"),
        ("35", "profit_actual_advance", "2026-01"),
        ("45", "profit_actual_advance", "2026-11"),
    ],
)
def test_profit_year_and_actual_months(code, rule, key):
    found = parse(profit(due(400, 600), period=code))

    assert amounts(found, rule) == {key: 1000_00}


def test_profit_warns_about_mixed_budgets_and_other_sections():
    found = parse(profit(due(-100, 300), "<НалПУДив/>"))

    assert amounts(found, "profit_advance") == {"2026-Q2": 200_00}
    first, second = found.warnings
    assert "разница" in first and "дивидендов" in second


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "пустой"),
        (b"%PDF-1.7", "не читается"),
        (b"<root/>", "не файл декларации"),
        (b"x" * (MAX_BYTES + 1), "больше 5 МБ"),
        (b'<!DOCTYPE a [<!ENTITY b "c">]><a>&b;</a>', "DTD"),
        (nds(knd="1152017"), "только декларации по НДС и по прибыли"),
        (nds(knd="1151006"), "основной файл"),
        (nds(period="34"), "налоговый период"),
        (profit(due(1, 1), period="22"), "налоговый период"),
        (profit(monthly((1, 1, 1), (1, 1, 1)), period="34"), "налоговый период"),
        (profit(), "нет сумм"),
        (nds(inn="123"), "ИНН"),
        (nds("-5"), "целым числом"),
    ],
)
def test_rejects_unsuitable_files(data, message):
    with pytest.raises(DeclarationError, match=message):
        parse(data)


@pytest.mark.parametrize("name", ["admin", "accountant"])
async def test_preview_changes_nothing_and_apply_writes_amounts(client, db, world, name):  # noqa: F811
    parts = await vat_tasks(db, world["company"])

    preview = await send(client, world[name], nds())

    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert (body["company_id"], body["title"], body["warnings"]) == (
        world["company"].id,
        "НДС за III квартал 2026",
        [],
    )
    assert [part["new_kopecks"] for part in body["parts"]] == [33_334_00] * 3
    assert [(await fresh(db, task)).amount_kopecks for task in parts] == [None, None, None]

    applied = await send(client, world[name], nds(), "apply")

    assert applied.status_code == 200, applied.text
    assert [part["current_kopecks"] for part in applied.json()["parts"]] == [None, None, None]
    assert [(await fresh(db, task)).amount_kopecks for task in parts] == [33_334_00] * 3
    record = await db.scalar(select(AuditLog).where(AuditLog.action == "task.declaration_amounts"))
    assert [row["task_id"] for row in record.payload["tasks"]] == [task.id for task in parts]


async def test_profit_writes_to_matching_payments_and_names_missing_ones(client, db, world):  # noqa: F811
    company = world["company"]
    advance = await payment(db, company, "profit_advance", "2026-Q2", date(2026, 7, 28))
    july = await payment(db, company, "profit_monthly", "2026-07", date(2026, 7, 28))
    data = profit(due(100, 200), monthly((10, 10, 10), (20, 20, 20)))

    response = await send(client, world["accountant"], data, "apply")

    assert response.status_code == 200, response.text
    assert (await fresh(db, advance)).amount_kopecks == 300_00
    assert (await fresh(db, july)).amount_kopecks == 30_00
    missing = response.json()["warnings"]
    assert len(missing) == 2 and "август 2026" in missing[0]


async def test_monthly_advances_switch_quarterly_company(client, db, world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(tasks, "today", lambda: date(2026, 11, 27))
    company = world["company"]
    company.main_regime, company.profit_advances_mode = "osno", "quarterly"
    await db.commit()
    await tasks.regenerate_company(db, company.id)
    data = profit(due(100, 200), monthly((10, 10, 10), (20, 20, 20)))
    monthly_tasks = select(Task).where(
        Task.company_id == company.id, Task.rule_code == "profit_monthly"
    )

    preview = await send(client, world["accountant"], data)

    body = preview.json()
    assert preview.status_code == 200, body
    assert body["switches_to_monthly"] and body["warnings"] == []
    new = [part for part in body["parts"] if part["task_id"] is None]
    assert [part["new_kopecks"] for part in new] == [30_00] * 3
    # предпросмотр не сохраняет ни настройку, ни платежи
    await db.refresh(company)
    assert company.profit_advances_mode == "quarterly"
    assert (await db.scalars(monthly_tasks)).all() == []

    applied = await send(client, world["accountant"], data, "apply")

    assert applied.json()["switches_to_monthly"], applied.text
    await db.refresh(company)
    assert company.profit_advances_mode == "monthly_by_quarter"
    written = {
        task.period_key: task.amount_kopecks
        for task in await db.scalars(monthly_tasks.execution_options(populate_existing=True))
    }
    assert [written[f"2026-{month:02d}"] for month in (7, 8, 9)] == [30_00] * 3
    again = await send(client, world["accountant"], data)
    assert again.json()["switches_to_monthly"] is False


@pytest.mark.parametrize(
    ("second", "reason"),
    [
        ({"status": "paid", "amount_kopecks": 5}, "уже оплачен"),
        ({"amount_overridden": True, "amount_kopecks": 5}, "сумма введена вручную"),
    ],
)
async def test_paid_and_manual_parts_stay(client, db, world, second, reason):  # noqa: F811
    parts = await vat_tasks(db, world["company"], **second)

    response = await send(client, world["accountant"], nds(), "apply")

    assert [part["kept"] for part in response.json()["parts"]] == ["", reason, ""]
    [warning] = response.json()["warnings"]
    assert "отличаются от декларации" in warning
    assert (await fresh(db, parts[1])).amount_kopecks == 5
    assert (await fresh(db, parts[0])).amount_kopecks == 33_334_00


@pytest.mark.parametrize(
    ("name", "status"),
    [("helper", 403), ("payer", 403), ("other_accountant", 422)],
)
async def test_who_may_not_load(client, db, world, name, status):  # noqa: F811
    parts = await vat_tasks(db, world["company"])

    for action in ("preview", "apply"):
        response = await send(client, world[name], nds(), action)
        assert response.status_code == status

    assert (await fresh(db, parts[0])).amount_kopecks is None


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (nds(inn=with_check_digits(f"{99:09d}")), "нет среди ваших"),
        (nds(period="22"), "НДС за II квартал 2026: платежей для этих сумм нет"),
    ],
)
async def test_explains_why_there_is_nowhere_to_write(client, db, world, data, message):  # noqa: F811
    await vat_tasks(db, world["company"])

    response = await send(client, world["accountant"], data)

    assert response.status_code == 422
    assert message in response.json()["detail"]
