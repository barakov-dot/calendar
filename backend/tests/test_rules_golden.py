"""«Золотые» даты 2026 года (PLAN.md, раздел 8) и сроки по статьям НК РФ."""

from datetime import date

import pytest

from app.services.rules.engine import occurrences
from tests.rules_helpers import book, company, dues, patent, schedule, work_calendar


def d(day: int, month: int, year: int = 2026) -> date:
    return date(year, month, day)


USN = company()
NDS = company(regime="osno")
AUSN = company(regime="ausn_income")


@pytest.mark.parametrize(
    ("target", "code", "period", "expected"),
    [
        (USN, "usn_notice", "2026-Q1", [d(27, 4)]),
        (USN, "usn_notice", "2026-Q2", [d(27, 7)]),
        (USN, "usn_notice", "2026-Q3", [d(26, 10)]),
        (USN, "usn_advance", "2026-Q2", [d(28, 7)]),
        (NDS, "nds_payment", "2026-Q2", [d(28, 7), d(28, 8), d(28, 9)]),
        (AUSN, "ausn_tax", "2026-10", [d(25, 11)]),
    ],
)
def test_golden_dates(target, code, period, expected):
    assert dues(schedule(target), code, period) == expected


OOO_OSNO = company(
    regime="osno",
    has_employees=True,
    has_property_avg=True,
    has_property_cadastral=True,
    has_property_advances=True,
    has_transport_tax=True,
    has_land_tax=True,
    has_trade_fee=True,
    has_tourist_tax=True,
)
MONTHLY = company(regime="osno", profit_advances_mode="monthly_by_quarter")
ACTUAL = company(regime="osno", profit_advances_mode="monthly_actual")
USN_IP = company("ip", "usn15", has_employees=True)
OSNO_IP = company("ip", "osno")
OSNO_IP_PROPERTY = company("ip", "osno", has_transport_tax=True, has_land_tax=True)


@pytest.mark.parametrize(
    ("target", "code", "period", "expected"),
    [
        # декларации и годовые платежи за 2025 год со сроком в 2026
        (USN, "usn_declaration_ooo", "2025", d(25, 3)),
        (USN, "usn_year_ooo", "2025", d(30, 3)),  # 28.03 — суббота
        (USN_IP, "usn_declaration_ip", "2025", d(27, 4)),
        (USN_IP, "usn_year_ip", "2025", d(28, 4)),
        (OOO_OSNO, "nds_declaration", "2025-Q4", d(26, 1)),
        (OOO_OSNO, "nds_declaration", "2026-Q1", d(27, 4)),
        (OOO_OSNO, "profit_declaration", "2026-Q1", d(27, 4)),
        (OOO_OSNO, "profit_advance", "2026-Q3", d(28, 10)),
        (OOO_OSNO, "profit_year_declaration", "2025", d(25, 3)),
        (OOO_OSNO, "profit_year", "2025", d(30, 3)),
        (MONTHLY, "profit_monthly", "2026-01", d(28, 1)),
        (MONTHLY, "profit_monthly", "2026-03", d(30, 3)),
        (MONTHLY, "profit_advance", "2026-Q1", d(28, 4)),
        (ACTUAL, "profit_actual_declaration", "2026-01", d(25, 2)),
        (ACTUAL, "profit_actual_advance", "2026-11", d(28, 12)),
        (OOO_OSNO, "property_avg_notice", "2026-Q1", d(27, 4)),
        (OOO_OSNO, "property_cad_year_notice", "2025", d(25, 2)),
        (OOO_OSNO, "property_declaration", "2025", d(25, 2)),
        (OOO_OSNO, "property_avg_year", "2025", d(2, 3)),  # 28.02 — суббота
        (OOO_OSNO, "property_cad_year", "2025", d(2, 3)),
        (OOO_OSNO, "accounting_report", "2025", d(31, 3)),
        (OOO_OSNO, "trade_fee_notice", "2026-Q1", d(27, 4)),
        (USN_IP, "efs1_stazh", "2025", d(26, 1)),
        (OSNO_IP_PROPERTY, "ip_transport_tax", "2025", d(1, 12)),
        (OSNO_IP_PROPERTY, "ip_land_tax", "2025", d(1, 12)),
        (OOO_OSNO, "transport_advance", "2026-Q1", d(28, 4)),
        (OOO_OSNO, "transport_year_notice", "2025", d(25, 2)),
        (OOO_OSNO, "land_year", "2025", d(2, 3)),
        (OOO_OSNO, "trade_fee", "2026-Q2", d(28, 7)),
        (OOO_OSNO, "tourist_declaration", "2026-Q3", d(26, 10)),
        (OOO_OSNO, "tourist_payment", "2026-Q3", d(28, 10)),
        (OSNO_IP, "ndfl_ip_advance", "2026-Q2", d(28, 7)),
        (OSNO_IP, "ndfl_ip_declaration", "2025", d(30, 4)),
        (OSNO_IP, "ndfl_ip_year", "2025", d(15, 7)),
        (USN_IP, "ip_fixed_contrib", "2026", d(28, 12)),
        (USN_IP, "ip_1pct", "2025", d(1, 7)),
        (USN_IP, "ndfl_notice", "2026-01", d(26, 1)),
        (USN_IP, "ndfl_payment", "2026-02", d(2, 3)),
        (USN_IP, "ndfl_end_notice", "2026-04", d(4, 5)),  # 3 мая — воскресенье
        (USN_IP, "ndfl_end_payment", "2026-04", d(5, 5)),
        (USN_IP, "ndfl_end_payment", "2026-11", d(7, 12)),
        (USN_IP, "ndfl_december", "2026-12", d(30, 12)),
        (USN_IP, "ndfl_december_notice", "2026-12", d(30, 12)),
        (USN_IP, "insurance_payment", "2025-12", d(28, 1)),
        (USN_IP, "insurance_payment", "2026-03", d(28, 4)),
        (USN_IP, "rsv", "2025-Q4", d(26, 1)),
        (USN_IP, "ndfl6", "2026-Q2", d(27, 7)),
        (USN_IP, "ndfl6_year", "2025", d(25, 2)),
        (USN_IP, "personal_info", "2026-03", d(27, 4)),
        (USN_IP, "efs1_s2", "2026-Q1", d(27, 4)),
        (USN_IP, "injury_contrib", "2026-01", d(16, 2)),
    ],
)
def test_dates_by_tax_code(target, code, period, expected):
    assert dues(schedule(target), code, period) == [expected]


def codes(target, patents=()) -> set[str]:
    return {item.rule_code for item in schedule(target, patents)}


EMPLOYER = {
    "ndfl_notice",
    "ndfl_payment",
    "ndfl_end_notice",
    "ndfl_end_payment",
    "ndfl_december_notice",
    "ndfl_december",
    "ndfl6",
    "ndfl6_year",
    "insurance_notice",
    "insurance_payment",
    "rsv",
    "personal_info",
    "efs1_s2",
    "injury_contrib",
    "efs1_stazh",
}
REPORT = {"accounting_report"}  # только организации
USN_COMMON = {"usn_notice", "usn_advance"}
USN_OOO = USN_COMMON | {"usn_declaration_ooo", "usn_year_ooo", "accounting_report"}
USN_OF_IP = USN_COMMON | {"usn_declaration_ip", "usn_year_ip"}
NDS_CODES = {"nds_declaration", "nds_payment"}
PROFIT_YEAR = {"profit_year", "profit_year_declaration"}
IP_CONTRIB = {"ip_fixed_contrib", "ip_1pct"}


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (company("ooo", "usn6"), USN_OOO),
        (company("ooo", "usn15", nds_payer=True), USN_OOO | NDS_CODES),
        (company("ooo", "usn6", has_employees=True), USN_OOO | EMPLOYER),
        (
            company("ooo", "osno", profit_advances_mode="quarterly"),
            NDS_CODES | PROFIT_YEAR | REPORT | {"profit_declaration", "profit_advance"},
        ),
        (
            MONTHLY,
            NDS_CODES
            | PROFIT_YEAR
            | REPORT
            | {"profit_declaration", "profit_advance", "profit_monthly"},
        ),
        (
            ACTUAL,
            NDS_CODES
            | PROFIT_YEAR
            | REPORT
            | {"profit_actual_declaration", "profit_actual_advance"},
        ),
        (company("ip", "usn6"), USN_OF_IP | IP_CONTRIB),
        (
            OSNO_IP,
            NDS_CODES
            | IP_CONTRIB
            | {"ndfl_ip_notice", "ndfl_ip_advance", "ndfl_ip_declaration", "ndfl_ip_year"},
        ),
        (company("ooo", "ausn_income"), {"ausn_tax", "accounting_report"}),
        (company("ip", "ausn_income_expense"), {"ausn_tax"}),
        (
            company("ip", "ausn_income", has_employees=True),
            {
                "ausn_tax",
                "ausn_injury",
                "ndfl_payment",
                "ndfl_end_payment",
                "ndfl_december",
                "efs1_stazh",
            },
        ),
        (
            company("ip", "ausn_income", has_employees=True, ausn_ndfl_tasks=False),
            {"ausn_tax", "ausn_injury", "efs1_stazh"},
        ),
    ],
)
def test_set_of_obligations_by_regime(target, expected):
    assert codes(target) == expected


def test_counts_for_employer_in_a_year():
    items = schedule(company("ooo", "usn6", has_employees=True))

    count = {code: len(dues(items, code)) for code in codes(company(has_employees=True))}

    assert count["insurance_notice"] == 8  # без третьих месяцев кварталов
    assert count["insurance_payment"] == 12
    assert count["personal_info"] == 12
    assert count["ndfl_payment"] == 12
    assert count["ndfl_end_payment"] == 11  # декабрь 2025 — январь … октябрь…ноябрь 2026
    assert count["ndfl_december"] == 1
    assert (count["rsv"], count["efs1_s2"], count["ndfl6"], count["ndfl6_year"]) == (4, 4, 3, 1)


def year_items(items, code):
    return [item for item in items if item.rule_code == code]


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        # до шести месяцев — одним платежом не позднее окончания
        (d(1, 3), d(31, 5), [(d(1, 6), 1, 100_000_00)]),  # 31.05 — воскресенье
        # от шести месяцев — треть за 90 дней и две трети к окончанию
        (d(12, 1), d(11, 11), [(d(13, 4), 1, 33_333_33), (d(11, 11), 2, 66_666_67)]),
        # окончание 31 декабря — платить до 28 декабря
        (d(1, 1), d(31, 12), [(d(1, 4), 1, 33_333_33), (d(28, 12), 2, 66_666_67)]),
        (d(1, 10), d(31, 12), [(d(28, 12), 1, 100_000_00)]),
    ],
)
def test_patent(start, end, expected):
    items = year_items(schedule(OSNO_IP, [patent(start, end)]), "patent_payment")

    assert [(i.due_date, i.part, i.amount_kopecks) for i in items] == expected


def test_patent_of_exactly_six_months_is_paid_in_two_parts():
    items = year_items(schedule(OSNO_IP, [patent(d(1, 1), d(30, 6))]), "patent_payment")

    assert [(i.due_date, i.part) for i in items] == [(d(1, 4), 1), (d(30, 6), 2)]


def test_two_patents_do_not_collide():
    patents = [patent(d(1, 1), d(31, 3), number=1), patent(d(1, 1), d(31, 3), number=2)]

    items = year_items(schedule(OSNO_IP, patents), "patent_payment")

    assert {item.period_key for item in items} == {"2026-P1", "2026-P2"}


def test_periods_without_rules_file_are_not_guessed():
    items = schedule(USN_IP, date_to=d(31, 12, 2028))

    assert max(item.period_year for item in items) == 2027
    # сроки периода 2027 года, наступающие в 2028, есть
    assert dues(items, "insurance_payment", "2027-12") == [d(28, 1, 2028)]


def test_each_year_uses_its_own_file():
    items = schedule(USN_IP, date_to=d(31, 12, 2027))

    assert dues(items, "insurance_payment", "2026-12") == [d(28, 1, 2027)]
    assert dues(items, "usn_year_ip", "2026") == [d(28, 4, 2027)]
    assert dues(items, "ip_1pct", "2026") == [d(1, 7, 2027)]


ASSETS = company(
    regime="osno",
    has_property_avg=True,
    has_property_cadastral=True,
    has_property_advances=True,
    has_transport_tax=True,
    has_land_tax=True,
)


@pytest.mark.parametrize(
    ("code", "period", "expected"),
    [
        # за 2026 год — по прежним правилам (425-ФЗ действует с периода 2027 года)
        ("transport_year", "2026", [d(1, 3, 2027)]),
        ("transport_year_notice", "2026", [d(25, 2, 2027)]),
        ("land_year", "2026", [d(1, 3, 2027)]),
        ("property_cad_year", "2026", [d(1, 3, 2027)]),
        # с 2027 года: аванс — 28-е второго месяца после квартала, год — 28 марта
        ("transport_advance", "2027-Q1", [d(28, 5, 2027)]),
        ("transport_advance", "2027-Q2", [d(30, 8, 2027)]),
        ("land_advance", "2027-Q3", [d(29, 11, 2027)]),
        ("land_year", "2027", [d(28, 3, 2028)]),
        ("transport_year", "2027", [d(28, 3, 2028)]),
        ("property_cad_advance", "2027-Q1", [d(28, 5, 2027)]),
        ("property_cad_year", "2027", [d(28, 3, 2028)]),
        # среднегодовая стоимость — без изменений
        ("property_avg_advance", "2027-Q1", [d(28, 4, 2027)]),
        ("property_avg_year", "2027", [d(28, 2, 2028)]),
        ("transport_notice", "2027-Q1", []),
        ("transport_year_notice", "2027", []),
        ("property_cad_notice", "2027-Q1", []),
        ("property_cad_year_notice", "2027", []),
    ],
)
def test_property_taxes_from_2027(code, period, expected):
    items = schedule(ASSETS, date_from=d(1, 1, 2027), date_to=d(31, 12, 2028))

    assert dues(items, code, period) == expected


def test_property_advances_are_off_by_default():
    target = company(
        regime="osno", has_property_cadastral=True, has_property_avg=True, has_land_tax=True
    )

    found = {item.rule_code for item in schedule(target, date_to=d(31, 12, 2027))}

    assert not {"land_advance", "property_avg_advance", "property_cad_advance"} & found
    assert {"land_year", "property_avg_year", "property_cad_year"} <= found


def test_dsv_report_only_with_flag():
    with_dsv = company(has_employees=True, has_dsv=True)

    assert dues(schedule(with_dsv), "efs1_dsv", "2026-Q1") == [d(27, 4)]
    assert not dues(schedule(company(has_employees=True)), "efs1_dsv")


def test_every_occurrence_key_is_unique_and_has_source():
    items = schedule(OOO_OSNO, date_to=d(31, 12, 2027))

    keys = [(i.rule_code, i.period_key, i.part) for i in items]
    assert len(keys) == len(set(keys))
    assert all(item.source_ref for item in items)
    assert all(item.due_date >= item.original_due_date for item in items)


def test_loaded_calendars_are_enough_for_current_year():
    calendar = work_calendar()

    occurrences(book, OOO_OSNO, [], calendar, d(1, 1), d(31, 3, 2027))

    assert calendar.missing_years == set()
