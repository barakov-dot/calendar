from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import AuditLog, Role, WorkDay
from app.services.calendar.workdays import (
    CalendarError,
    WorkCalendar,
    load_calendar,
    load_missing_years,
    parse_calendar,
    read_calendar_file,
)
from tests.factories import auth, make_user
from tests.rules_helpers import CALENDAR_DIR, work_calendar

# Число рабочих дней по месяцам — производственные календари КонсультантПлюс.
WORKDAYS = {
    2026: [15, 19, 21, 22, 19, 21, 23, 21, 22, 22, 20, 22],
    2027: [15, 19, 22, 22, 19, 21, 22, 22, 22, 21, 20, 22],
}


@pytest.mark.parametrize("year", WORKDAYS)
def test_calendar_files_match_official_month_counts(year):
    days = read_calendar_file(CALENDAR_DIR / f"{year}.json").days()

    counts = [sum(w for d, w in days.items() if d.month == month) for month in range(1, 13)]

    assert counts == WORKDAYS[year]
    assert sum(counts) == 247


@pytest.mark.parametrize(
    ("day", "shifted"),
    [
        (date(2026, 4, 25), date(2026, 4, 27)),  # суббота
        (date(2026, 4, 28), date(2026, 4, 28)),  # рабочий день
        (date(2026, 1, 5), date(2026, 1, 12)),  # новогодние каникулы
        (date(2026, 12, 31), date(2027, 1, 11)),  # через границу года
        (date(2027, 2, 20), date(2027, 2, 20)),  # рабочая суббота
    ],
)
def test_shift_to_workday(day, shifted):
    assert work_calendar().shift_to_workday(day) == shifted


def test_last_workday_of_year():
    assert work_calendar().last_workday_of_year(2026) == date(2026, 12, 30)


def test_without_calendar_week_is_monday_to_friday_and_year_is_reported():
    empty = WorkCalendar({})

    assert empty.shift_to_workday(date(2030, 6, 1)) == date(2030, 6, 3)
    assert empty.missing_years == {2030}


VALID = {"year": 2028, "source": "тест", "days_off": ["2028-01-03"]}


@pytest.mark.parametrize(
    "data",
    [
        VALID | {"days_off": ["2027-01-04"]},
        VALID | {"days_off": ["2028-01-01"]},  # суббота
        VALID | {"working_weekends": ["2028-01-03"]},  # понедельник
        VALID | {"source": ""},
        VALID | {"extra": 1},
        [],
    ],
)
def test_invalid_calendar(data):
    with pytest.raises(CalendarError):
        parse_calendar(data)


async def test_load_missing_years_once(db):
    assert await load_missing_years(db, CALENDAR_DIR) == [2026, 2027]
    assert await load_missing_years(db, CALENDAR_DIR) == []

    assert len((await db.scalars(select(WorkDay))).all()) == 730
    assert (await load_calendar(db)).is_workday(date(2026, 1, 9)) is False


async def test_broken_calendar_file(db, tmp_path: Path):
    (tmp_path / "2028.json").write_text("{")

    with pytest.raises(CalendarError, match="2028.json"):
        await load_missing_years(db, tmp_path)


@pytest.mark.usefixtures("secrets")
async def test_upload_through_api(client, db):
    admin = auth(await make_user(db, 1, Role.ADMIN))
    accountant = auth(await make_user(db, 2))
    url = "/api/admin/calendar/2028"

    assert (await client.post(url, json=VALID, headers=accountant)).status_code == 403
    assert (await client.get("/api/admin/calendar", headers=accountant)).status_code == 403
    wrong_year = await client.post("/api/admin/calendar/2029", json=VALID, headers=admin)
    assert wrong_year.status_code == 422
    for _ in range(2):  # повторная загрузка заменяет год
        assert (await client.post(url, json=VALID, headers=admin)).status_code == 200

    [year] = (await client.get("/api/admin/calendar", headers=admin)).json()
    assert (year["year"], year["source"]) == (2028, "тест")
    assert year["workdays"] + year["days_off"] == 366
    actions = (await db.scalars(select(AuditLog.action))).all()
    assert actions == ["calendar.upload"] * 2
