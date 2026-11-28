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
IP_INN = with_check_digits("0000000042")


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
        (nds(knd="1152016"), "Поддерживаются декларации"),
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


def usn(due="1000", base="1", period="34", person=True, year="2025", **header) -> bytes:
    taxpayer = (
        f'<НПФЛ ИННФЛ="{IP_INN}"><ФИО Фамилия="Петров" Имя="Пётр"/></НПФЛ>'
        if person
        else f'<НПЮЛ НаимОрг="ООО" ИННЮЛ="{INN}"/>'
    )
    text = f"""<?xml version="1.0" encoding="windows-1251"?>
<Файл><Документ КНД="1152017" Период="{period}" ОтчетГод="{year}" НомКорр="0">
<СвНП>{taxpayer}</СвНП><УСН ОбНал="{base}">
<СумНалПУ_НП ОКТМО="45000000" АвПУКв="100" АвПУУменПг="200" АвПУУмен9м="300" НалПУУменПер="{due}"/>
</УСН></Документ></Файл>"""
    return text.encode("cp1251")


def line(amount="500", quarter="03", kbk="18210501011011000110", period="34", year="2026"):
    return (
        f'<УвИсчСумНалог ОКТМО="45000000" КБК="{kbk}" СумНалогАванс="{amount}" '
        f'Период="{period}" НомерМесКварт="{quarter}" Год="{year}"/>'
    )


def notice(*lines) -> bytes:
    text = f"""<?xml version="1.0" encoding="windows-1251"?>
<Файл><Документ КНД="1110355" ДатаДок="24.10.2026">
<СвНП><НПИП ИННФЛ="{IP_INN}"/></СвНП>{"".join(lines)}</Документ></Файл>"""
    return text.encode("cp1251")


@pytest.mark.parametrize(("quarter", "key"), [("01", "Q1"), ("02", "Q2"), ("03", "Q3")])
def test_notice_gives_quarterly_usn_advance(quarter, key):
    found = parse(notice(line(quarter=quarter)))

    assert (found.inn, found.warnings) == (IP_INN, ())
    assert amounts(found, "usn_advance") == {f"2026-{key}": 500_00}


def test_notice_sums_lines_and_skips_other_taxes():
    found = parse(
        notice(
            line("500"),
            line("70", kbk="18210501021011000110"),
            line("40", kbk="18210102020011000110"),
            # НДФЛ с зарплаты и страховые взносы не загружаются
            line("9", kbk="18210102010011000110", period="21", quarter="01"),
            line("8", kbk="18210201000011000160", period="21", quarter="02"),
        )
    )

    assert amounts(found, "usn_advance") == {"2026-Q3": 570_00}
    assert amounts(found, "ndfl_ip_advance") == {"2026-Q3": 40_00}
    assert "2" in found.warnings[0]
    assert found.title == "Уведомление об авансах за 9 месяцев 2026"


def test_notice_reduction_means_nothing_to_pay():
    found = parse(notice(line("-300", quarter="02")))

    assert amounts(found, "usn_advance") == {"2026-Q2": 0}
    assert found.totals == (("Аванс УСН за полугодие 2026: к уменьшению", 300_00),)


@pytest.mark.parametrize(("person", "rule"), [(True, "usn_year_ip"), (False, "usn_year_ooo")])
def test_usn_declaration_gives_year_payment_only(person, rule):
    found = parse(usn(person=person))

    assert [(item.rule_code, item.period_key, item.amount_kopecks) for item in found.items] == [
        (rule, "2025", 1000_00)
    ]


def test_usn_reduction_means_nothing_to_pay():
    found = parse(usn("-250"))

    assert found.items[0].amount_kopecks == 0
    assert found.totals == (("К уменьшению за год", 250_00),)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (usn(base="2"), "только декларация УСН «Доходы»"),
        (usn(period="21"), "налоговый период"),
        (notice(), "нет сумм"),
        (notice(line(kbk="18210102010011000110")), "нет авансов по УСН"),
        (notice(line("abc")), "целым числом"),
    ],
)
def test_rejects_unsuitable_usn_files(data, message):
    with pytest.raises(DeclarationError, match=message):
        parse(data)


async def test_usn_files_fill_ip_payments(client, db, world):  # noqa: F811
    company = world["company"]
    company.entity_type, company.inn = "ip", IP_INN
    await db.commit()
    advance = await payment(db, company, "usn_advance", "2026-Q3", date(2026, 10, 28))
    yearly = await payment(db, company, "usn_year_ip", "2025", date(2026, 4, 28))
    headers = world["accountant"]

    for data in (notice(line()), usn()):
        response = await send(client, headers, data, "apply")
        assert response.status_code == 200, response.text

    assert (await fresh(db, advance)).amount_kopecks == 500_00
    assert (await fresh(db, yearly)).amount_kopecks == 1000_00


PROPERTY_KBK = "18210602010021000110"
TRANSPORT_KBK = "18210604011021000110"
LAND_KBK = "18210606032041000110"


def company_notice(*lines) -> bytes:
    return notice(*lines).replace(
        f'<НПИП ИННФЛ="{IP_INN}"/>'.encode("cp1251"),
        f'<НПЮЛ ИННЮЛ="{INN}" КПП="000001001"/>'.encode("cp1251"),
    )


def test_notice_reads_property_transport_and_land():
    found = parse(
        company_notice(
            line("100", kbk=PROPERTY_KBK),
            line("20", kbk=TRANSPORT_KBK),
            line("3", kbk=LAND_KBK),
            line("40", kbk=TRANSPORT_KBK, quarter="04"),
            # транспортный налог физлиц сюда не относится, у УСН номера 04 нет
            line("9", kbk="18210604012021000110"),
            line("8", quarter="04"),
        )
    )

    assert {(item.rule_code, item.period_key): item.amount_kopecks for item in found.items} == {
        ("property_advance", "2026-Q3"): 100_00,
        ("transport_advance", "2026-Q3"): 20_00,
        ("land_advance", "2026-Q3"): 3_00,
        ("transport_year", "2026"): 40_00,
    }
    assert ("Аванс: транспортный налог за III квартал 2026", 20_00) in found.totals
    assert "2" in found.warnings[0]


async def osno_company(db, world, **flags):  # noqa: F811
    company = world["company"]
    company.main_regime = "osno"
    for name, value in flags.items():
        setattr(company, name, value)
    await db.commit()
    await tasks.regenerate_company(db, company.id)
    return company


async def written(db, company) -> dict:
    rows = await db.scalars(
        select(Task)
        .where(Task.company_id == company.id, Task.amount_kopecks.is_not(None))
        .execution_options(populate_existing=True)
    )
    return {(task.rule_code, task.period_key): task.amount_kopecks for task in rows}


async def test_notice_marks_missing_taxes_only_when_applied(client, db, world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(tasks, "today", lambda: date(2026, 11, 28))
    company = await osno_company(db, world)
    data = company_notice(line("100", kbk=PROPERTY_KBK), line("20", kbk=TRANSPORT_KBK))

    preview = (await send(client, world["accountant"], data)).json()

    assert preview["enables"] == [
        "Имущество по среднегодовой стоимости",
        "Транспортный налог",
        "Платит авансы по имущественным налогам",
    ]
    assert [part["task_id"] for part in preview["parts"]] == [None, None]
    await db.refresh(company)
    assert company.has_transport_tax is False

    await send(client, world["accountant"], data, "apply")

    await db.refresh(company)
    assert (company.has_property_avg, company.has_transport_tax, company.has_property_advances) == (
        True,
        True,
        True,
    )
    assert await written(db, company) == {
        ("property_avg_advance", "2026-Q3"): 100_00,
        ("transport_advance", "2026-Q3"): 20_00,
    }


@pytest.mark.parametrize(
    ("flags", "rule", "warned"),
    [
        ({"has_property_cadastral": True}, "property_cad_advance", False),
        ({"has_property_avg": True}, "property_avg_advance", False),
        (
            {"has_property_avg": True, "has_property_cadastral": True},
            "property_avg_advance",
            True,
        ),
    ],
)
async def test_property_goes_to_the_kind_in_company_card(
    client,
    db,
    world,  # noqa: F811
    monkeypatch,
    flags,
    rule,
    warned,  # noqa: F811
):
    monkeypatch.setattr(tasks, "today", lambda: date(2026, 11, 28))
    company = await osno_company(db, world, has_property_advances=True, **flags)

    response = await send(
        client, world["accountant"], company_notice(line("100", kbk=PROPERTY_KBK)), "apply"
    )

    assert response.json()["enables"] == [], response.text
    assert await written(db, company) == {(rule, "2026-Q3"): 100_00}
    assert any("кадастровой" in text for text in response.json()["warnings"]) == warned
