from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_config
from app.core.settings_store import get_store
from app.models import CompanyMember, Notification, NotificationSettings, Role, Task
from app.services.calendar.workdays import load_missing_years
from app.services.notify.messages import marker
from app.services.notify.planner import plan, workdays_until
from app.services.notify.queue import enqueue
from app.services.notify.sender import deliver
from app.services.telegram.factory import create_bot, resolve_proxy
from tests.factories import link_client, make_company, make_user
from tests.fakes import FakeSocks5, FakeTelegram
from tests.rules_helpers import CALENDAR_DIR, work_calendar

# четверг, 10:00 по Москве
NOW = datetime(2026, 11, 26, 7, 0, tzinfo=UTC)
TODAY = date(2026, 11, 26)


def day(offset: int) -> date:
    return TODAY + timedelta(days=offset)


async def add_task(db, company, due: date, **fields) -> Task:
    values = {
        "company_id": company.id if company else None,
        "source": "custom",
        "kind": "payment",
        "title": "Налог",
        "due_date": due,
        "original_due_date": due,
        "client_visible": True,
        "amount_kopecks": 3333334,
    } | fields
    task = Task(**values)
    db.add(task)
    await db.commit()
    return task


@pytest.fixture
async def world(db, secrets):
    await load_missing_years(db, CALENDAR_DIR)
    get_store().update({"telegram": {"mini_app_url": "https://cal.example/"}})
    accountant = await make_user(db, 100, first_name="Борис")
    payer = await make_user(db, 200, Role.CLIENT, first_name="Пётр")
    viewer = await make_user(db, 300, Role.CLIENT)
    company = await make_company(db, accountant, short_name="ООО «Ромашка»")
    await link_client(db, company, payer, can_mark_paid=True)
    await link_client(db, company, viewer)
    return locals()


async def queued(db) -> set[tuple[int, str, int | None]]:
    rows = await db.scalars(select(Notification).execution_options(populate_existing=True))
    return {(row.user_id, row.type, row.task_id) for row in rows}


async def run_plan(db, now=NOW) -> set:
    await plan(db, get_store().get(), now)
    return await queued(db)


@pytest.fixture
async def telegram():
    async with FakeTelegram() as fake:
        yield fake


@pytest.fixture
async def bot(telegram, secrets):
    bot = create_bot(get_config(), None, telegram.api("127.0.0.1"))
    yield bot
    await bot.session.close()


async def send(db, bot, now=NOW) -> int:
    return await deliver(db, bot, get_store().get(), now, pause=0)


async def statuses(db) -> list[str]:
    rows = await db.scalars(
        select(Notification).order_by(Notification.id).execution_options(populate_existing=True)
    )
    return [row.status for row in rows]


def test_workdays_until_counts_working_days_only():
    calendar = work_calendar()

    assert workdays_until(calendar, TODAY, day(0)) == 0
    assert workdays_until(calendar, TODAY, day(4)) == 2  # пт и пн
    assert workdays_until(calendar, date(2026, 12, 30), date(2027, 1, 12)) == 2


async def test_client_reminders_by_offsets(db, world):
    company, payer, viewer = world["company"], world["payer"], world["viewer"]
    due = {offset: await add_task(db, company, day(offset)) for offset in (0, 1, 2, 3, 7, 8)}
    hidden = await add_task(db, company, day(3), client_visible=False)
    report = await add_task(db, company, day(3), kind="report", amount_kopecks=None)
    paid = await add_task(db, company, day(3), status="paid")

    found = await run_plan(db)

    reminded = {task_id for user, kind, task_id in found if (user, kind) == (payer.id, "reminder")}
    assert reminded == {due[0].id, due[1].id, due[3].id, due[7].id}
    assert {t for u, k, t in found if (u, k) == (viewer.id, "reminder")} == reminded
    assert not reminded & {hidden.id, report.id, paid.id}
    assert await run_plan(db) == found  # повторный запуск без дублей


async def test_personal_offsets_and_switches(db, world):
    company, payer, viewer = world["company"], world["payer"], world["viewer"]
    two = await add_task(db, company, day(2))
    today = await add_task(db, company, day(0))
    db.add(NotificationSettings(user_id=payer.id, offsets_days=[2], on_due_day=False))
    member = await db.get_one(CompanyMember, (company.id, viewer.id))
    member.receive_reminders = False
    await db.commit()

    found = {(u, t) for u, k, t in await run_plan(db) if k == "reminder"}

    assert found == {(payer.id, two.id)}
    assert (payer.id, today.id) not in found


async def test_nothing_at_night(db, world):
    await add_task(db, world["company"], day(0), amount_kopecks=None, needs_amount=True)

    assert await run_plan(db, datetime(2026, 11, 26, 3, 0, tzinfo=UTC)) == set()


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (datetime(2026, 11, 26, 5, 59, tzinfo=UTC), False),  # 08:59
        (datetime(2026, 11, 26, 6, 0, tzinfo=UTC), True),  # 09:00
        (datetime(2026, 11, 28, 7, 0, tzinfo=UTC), False),  # суббота
    ],
)
async def test_digest_time_and_workdays(db, world, moment, expected):
    found = await run_plan(db, moment)

    assert ((world["accountant"].id, "digest", None) in found) is expected


async def test_digest_is_not_duplicated_and_can_be_disabled(db, world):
    await run_plan(db)
    await run_plan(db)
    assert [k for _, k, _ in await queued(db)].count("digest") == 1

    get_store().update({"notifications": {"digest_workdays_only": False}})
    db.add(NotificationSettings(user_id=world["accountant"].id, daily_digest=False))
    await db.commit()
    saturday = datetime(2026, 11, 28, 7, 0, tzinfo=UTC)
    assert [k for _, k, _ in await run_plan(db, saturday)].count("digest") == 1


async def test_fill_amount_and_overdue(db, world):
    company, accountant, payer = world["company"], world["accountant"], world["payer"]
    soon = await add_task(db, company, day(6), amount_kopecks=None, needs_amount=True)
    far = await add_task(db, company, day(14), amount_kopecks=None, needs_amount=True)
    filled = await add_task(db, company, day(5), needs_amount=True)
    late = await add_task(db, company, day(-1))
    old = await add_task(db, company, day(-10))

    found = await run_plan(db)

    assert {t for _, k, t in found if k == "fill_amount"} == {soon.id}
    assert {(u, t) for u, k, t in found if k == "overdue"} == {
        (accountant.id, late.id),
        (payer.id, late.id),  # клиенту — только тому, кто платит сам
    }
    assert not {far.id, filled.id, old.id} & {t for _, k, t in found if k == "overdue"}


async def test_unreachable_users_get_nothing(db, world):
    world["accountant"].bot_blocked = True
    world["payer"].is_active = False
    world["viewer"].telegram_id = -5
    await db.commit()
    await add_task(db, world["company"], day(0))

    assert await run_plan(db) == set()


async def test_messages_and_buttons(db, world, bot, telegram):
    await add_task(db, world["company"], date(2026, 12, 3), client_note="Реквизиты у бухгалтера")
    await run_plan(db)

    await send(db, bot)

    sent = {
        chat: (text, kb) for (chat, text), kb in zip(telegram.sent, telegram.keyboards, strict=True)
    }
    text, buttons = sent[200]
    assert text.startswith("🟢 ООО «Ромашка»: до 03.12 оплатить — Налог — 33 333,34 ₽")
    assert "Реквизиты у бухгалтера" in text
    assert [b["text"] for b in buttons] == ["Оплатил", "Открыть календарь"]
    assert buttons[1]["web_app"]["url"] == "https://cal.example/"
    assert [b["text"] for b in sent[300][1]] == ["Открыть календарь"]
    digest, _ = sent[100]
    assert "Ближайшие 7 дней: 1" in digest
    assert set(await statuses(db)) == {"sent"}
    assert await send(db, bot) == 0


async def test_empty_digest_is_not_sent(db, world, bot, telegram):
    await run_plan(db)

    assert await send(db, bot) == 0
    assert await statuses(db) == ["skipped"]


async def test_paid_task_stops_reminders(db, world, bot, telegram):
    task = await add_task(db, world["company"], day(1))
    await run_plan(db)
    task.status = "paid"
    await db.commit()

    await send(db, bot)

    assert telegram.sent == []
    assert set(await statuses(db)) == {"skipped"}


async def test_accountant_messages_are_grouped(db, world, bot, telegram):
    for number in range(3):
        await add_task(
            db,
            world["company"],
            day(2),
            title=f"П{number}",
            amount_kopecks=None,
            needs_amount=True,
            client_visible=False,
        )
    await run_plan(db)

    await send(db, bot)

    grouped = [text for chat, text in telegram.sent if text.startswith("Заполните сумму: 3")]
    assert len(grouped) == 1
    assert all(f"П{number}" in grouped[0] for number in range(3))


async def test_queue_waits_while_telegram_is_unavailable(db, world, telegram, secrets):
    task = await add_task(db, world["company"], day(1))
    await enqueue(db, world["payer"].id, "reminder", TODAY, task.id)
    await db.commit()
    async with FakeSocks5() as dead:
        port = dead.port
    settings = get_store().update(
        {"telegram": {"proxy": {"enabled": True, "host": "127.0.0.1", "port": port}}}
    )
    broken = create_bot(get_config(), resolve_proxy(settings, None), telegram.api())

    assert await send(db, broken) == 0
    await broken.session.close()
    row = await db.scalar(select(Notification).execution_options(populate_existing=True))
    assert (row.status, row.attempts) == ("pending", 1)
    assert row.next_attempt_at == NOW + timedelta(seconds=30)

    working = create_bot(get_config(), None, telegram.api("127.0.0.1"))
    assert await send(db, working, NOW + timedelta(seconds=10)) == 0  # ещё рано
    assert await send(db, working, NOW + timedelta(hours=2)) == 1
    await working.session.close()
    assert await statuses(db) == ["sent"]


async def test_stale_reminder_is_dropped_after_outage(db, world, bot, telegram):
    task = await add_task(db, world["company"], day(1))
    await enqueue(db, world["payer"].id, "reminder", TODAY, task.id)
    await enqueue(db, world["accountant"].id, "digest", TODAY)
    await db.commit()

    await send(db, bot, NOW + timedelta(days=3))

    assert telegram.sent == []
    assert await statuses(db) == ["skipped", "skipped"]


async def test_blocked_bot(db, world, bot, telegram):
    await add_task(db, world["company"], day(1))
    await run_plan(db)
    telegram.failures[200] = (403, "Forbidden: bot was blocked by the user", {})

    await send(db, bot)

    await db.refresh(world["payer"])
    assert world["payer"].bot_blocked is True
    assert 300 in [chat for chat, _ in telegram.sent]  # остальные получили
    assert "failed" in await statuses(db)


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        ((429, "Too Many Requests: retry after 7", {"retry_after": 7}), "pending"),
        ((400, "Bad Request: chat not found", {}), "failed"),
    ],
)
async def test_telegram_errors(db, world, bot, telegram, failure, status):
    task = await add_task(db, world["company"], day(1))
    await enqueue(db, world["payer"].id, "reminder", TODAY, task.id)
    await db.commit()
    telegram.failures[200] = failure

    await send(db, bot)

    assert await statuses(db) == [status]
    if status == "pending":
        row = await db.scalar(select(Notification).execution_options(populate_existing=True))
        assert row.next_attempt_at == NOW + timedelta(seconds=7)


async def test_unlinked_client_gets_nothing(db, world, bot, telegram):
    task = await add_task(db, world["company"], day(1))
    outsider = await make_user(db, 400, Role.CLIENT)
    await enqueue(db, outsider.id, "reminder", TODAY, task.id)
    await db.commit()

    await send(db, bot)

    assert telegram.sent == []
    assert await statuses(db) == ["skipped"]


@pytest.mark.parametrize(
    ("left", "circle"),
    [(30, "🟢"), (7, "🟢"), (6, "🟡"), (2, "🟡"), (1, "🔴"), (0, "🔴"), (-1, "🔴")],
)
def test_colour_of_circle(left, circle):
    assert marker(day(left), TODAY) == circle


async def test_circles_in_every_list(db, world, bot, telegram):
    for offset in (-1, 3, 7):
        await add_task(db, world["company"], day(offset), title=f"Через {offset}")
    await run_plan(db)

    await send(db, bot)

    digest = next(text for chat, text in telegram.sent if text.startswith("Доброе утро"))
    lines = {line.split(" ")[0] for line in digest.splitlines() if "Через" in line}
    assert lines == {"🔴", "🟡", "🟢"}
    reminders = [text for chat, text in telegram.sent if chat == 200]
    assert {text[0] for text in reminders} == {"🔴", "🟡", "🟢"}


@pytest.mark.parametrize("rule", ["salary_advance", "salary_payment"])
async def test_salary_reminder_only_on_payday(db, world, rule):
    company, payer = world["company"], world["payer"]
    tasks_ = {
        offset: await add_task(
            db, company, day(offset), source="rule", rule_code=rule, period_key=str(offset)
        )
        for offset in (-1, 0, 1, 3, 7)
    }
    # и тому, кто отключил напоминание в день срока для налогов
    db.add(NotificationSettings(user_id=payer.id, on_due_day=False))
    await db.commit()

    found = await run_plan(db)

    mine = {(kind, task_id) for user, kind, task_id in found if user == payer.id}
    assert mine == {("reminder", tasks_[0].id)}
