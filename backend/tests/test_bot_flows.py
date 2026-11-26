from datetime import UTC, datetime, timedelta

import pytest
from aiogram import Bot
from sqlalchemy import select, update

from app.bot.dispatcher import build_dispatcher
from app.bot.handlers import (
    ACCESS_BY_INVITE,
    CONSENT_TEXT,
    GREETINGS,
    LOGIN_CANCELLED,
    LOGIN_CONFIRMED,
    LOGIN_EXPIRED,
)
from app.bot.payments import MARKED, NOTHING, UNMARKED
from app.core.config import get_config
from app.core.settings_store import get_store
from app.models import AuditLog, CompanyMember, Invite, InviteKind, Role, Task, User
from app.services import invites, login
from app.services.tasks import today
from app.services.telegram.factory import create_bot
from tests.factories import link_client, make_company, make_user
from tests.fakes import FakeTelegram

USER_ID = 500


class Chat:
    """Диалог пользователя с ботом без polling."""

    def __init__(self, telegram: FakeTelegram, bot: Bot) -> None:
        self.telegram = telegram
        self.bot = bot
        self.dispatcher = build_dispatcher(get_store())
        self._update_id = 0

    async def start(self, payload: str = "", user_id: int = USER_ID) -> str:
        self._update_id += 1
        text = f"/start {payload}".strip()
        self.telegram.send_start(self._update_id, user_id, text)
        await self.dispatcher.feed_raw_update(self.bot, self.telegram.updates[-1])
        return self.telegram.sent[-1][1]

    async def press(self, data: str, user_id: int = USER_ID) -> None:
        self._update_id += 1
        update_ = self.telegram.send_callback(self._update_id, user_id, data)
        await self.dispatcher.feed_raw_update(self.bot, update_)

    async def command(self, text: str, user_id: int) -> str:
        self._update_id += 1
        self.telegram.send_start(self._update_id, user_id, text)
        self.telegram.updates[-1]["message"]["entities"][0]["length"] = len(text)
        await self.dispatcher.feed_raw_update(self.bot, self.telegram.updates[-1])
        return self.telegram.sent[-1][1]

    async def membership(self, status: str, user_id: int = USER_ID) -> None:
        self._update_id += 1
        user = {"id": user_id, "is_bot": False, "first_name": "Тест"}
        bot_user = {"id": 123456, "is_bot": True, "first_name": "Bot"}
        old = {"user": bot_user, "status": "member"}
        new = {"user": bot_user, "status": status}
        if status == "kicked":
            new["until_date"] = 0
        update_ = {
            "update_id": self._update_id,
            "my_chat_member": {
                "chat": {"id": user_id, "type": "private"},
                "from": user,
                "date": 1_700_000_000,
                "old_chat_member": old,
                "new_chat_member": new,
            },
        }
        await self.dispatcher.feed_raw_update(self.bot, update_)

    def button(self, text: str) -> str:
        [found] = [b for b in self.telegram.keyboards[-1] if b["text"] == text]
        assert len(found["callback_data"].encode()) <= 64
        return found["callback_data"]


@pytest.fixture
async def chat(secrets):
    async with FakeTelegram() as telegram:
        bot = create_bot(get_config(), None, telegram.api("127.0.0.1"))
        yield Chat(telegram, bot)
        await bot.session.close()


async def new_invite(db) -> Invite:
    admin = await make_user(db, 1, Role.ADMIN)
    return await invites.create(db, InviteKind.ACCOUNTANT, admin)


async def users(db) -> dict[int, User]:
    db.expire_all()
    return {user.telegram_id: user for user in await db.scalars(select(User))}


async def test_stranger_is_not_saved(chat, db):
    assert await chat.start() == ACCESS_BY_INVITE
    assert await chat.start("login_whatever") == ACCESS_BY_INVITE
    assert await users(db) == {}


async def test_invite_creates_user_only_after_consent(chat, db):
    invite = await new_invite(db)

    assert await chat.start(f"inv_{invite.token}") == CONSENT_TEXT
    assert USER_ID not in await users(db)

    await chat.press(chat.button("Согласен"))

    user = (await users(db))[USER_ID]
    assert (user.role, user.first_name) == ("accountant", "Тест")
    assert user.pd_consent_at is not None
    assert chat.telegram.edited == [GREETINGS[Role.ACCOUNTANT]]
    await db.refresh(invite)
    assert invite.used_by == user.id
    actions = (await db.scalars(select(AuditLog.action).order_by(AuditLog.id))).all()
    assert actions == ["invite.create", "invite.accept"]


async def test_policy_link_is_shown(chat, db):
    get_store().update({"company": {"privacy_policy_url": "https://example.org/policy"}})
    invite = await new_invite(db)

    await chat.start(f"inv_{invite.token}")

    assert chat.telegram.keyboards[-1][0]["url"] == "https://example.org/policy"


async def test_invite_works_only_once(chat, db):
    invite = await new_invite(db)
    await chat.start(f"inv_{invite.token}")
    agree = chat.button("Согласен")
    await chat.press(agree)

    assert await chat.start(f"inv_{invite.token}", user_id=600) == invites.INVALID
    await chat.press(agree, user_id=600)  # кнопку переслали другому

    assert 600 not in await users(db)
    assert chat.telegram.edited[-1] == invites.INVALID


@pytest.mark.parametrize(
    "spoil",
    [
        {"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
        {"revoked_at": datetime.now(UTC)},
    ],
)
async def test_expired_or_revoked_invite(chat, db, spoil):
    invite = await new_invite(db)
    await db.execute(update(Invite).values(**spoil))
    await db.commit()

    assert await chat.start(f"inv_{invite.token}") == invites.INVALID
    await chat.press(f"agree:inv_{invite.token}")

    assert USER_ID not in await users(db)


async def test_invite_does_not_change_existing_role(chat, db):
    invite = await new_invite(db)
    await make_user(db, USER_ID, Role.CLIENT)

    reply = await chat.start(f"inv_{invite.token}")

    assert "другой ролью" in reply
    assert (await users(db))[USER_ID].role == "client"
    await db.refresh(invite)
    assert invite.used_at is None


async def test_invite_does_not_reactivate_disabled_user(chat, db):
    invite = await new_invite(db)
    await make_user(db, USER_ID, is_active=False)

    assert "отключён" in await chat.start(f"inv_{invite.token}")
    await chat.press(f"agree:inv_{invite.token}")

    assert (await users(db))[USER_ID].is_active is False


async def test_site_login_confirmation(chat, db):
    await make_user(db, USER_ID)
    request = await login.create_request(db)

    reply = await chat.start(f"login_{request.nonce}")
    assert login.comparison_code(request.nonce) in reply
    assert await login.consume(db, request.nonce) is None  # без нажатия кнопки входа нет

    await chat.press(chat.button("Войти на сайт"))

    assert chat.telegram.edited == [LOGIN_CONFIRMED]
    assert await login.consume(db, request.nonce) == USER_ID


async def test_site_login_cancel_and_expired(chat, db):
    await make_user(db, USER_ID)
    request = await login.create_request(db)
    await chat.start(f"login_{request.nonce}")

    await chat.press(chat.button("Это не я"))
    assert await login.consume(db, request.nonce) is None
    assert await chat.start("login_unknown") == LOGIN_EXPIRED
    await chat.press("login:unknown")

    assert chat.telegram.edited == [LOGIN_CANCELLED, LOGIN_EXPIRED]


async def test_forged_login_button_from_stranger(chat, db):
    request = await login.create_request(db)

    await chat.press(f"login:{request.nonce}")

    assert chat.telegram.edited == [ACCESS_BY_INVITE]
    assert await login.consume(db, request.nonce) is None


async def test_seeded_admin_consents_then_logs_in(chat, db):
    await make_user(db, USER_ID, Role.ADMIN, pd_consent_at=None)
    nonce = (await login.create_request(db)).nonce

    assert await chat.start(f"login_{nonce}") == CONSENT_TEXT
    await chat.press(f"login:{nonce}")  # без согласия подтвердить нельзя
    assert await login.consume(db, nonce) is None

    await chat.start(f"login_{nonce}")
    await chat.press(chat.button("Согласен"))
    await chat.press(chat.button("Войти на сайт"))

    assert (await users(db))[USER_ID].pd_consent_at is not None
    assert await login.consume(db, nonce) == USER_ID


async def test_client_invite_through_bot(chat, db):
    accountant = await make_user(db, 2)
    company = await make_company(db, accountant, short_name="Ромашка")
    invite = await invites.create(db, InviteKind.CLIENT, accountant, company_id=company.id)

    assert await chat.start(f"inv_{invite.token}") == CONSENT_TEXT
    await chat.press(chat.button("Согласен"))

    assert "Вы подключены к компании «Ромашка»" in chat.telegram.edited[-1]
    members = (await db.scalars(select(CompanyMember.company_id))).all()
    assert members == [company.id]
    assert (await users(db))[USER_ID].role == "client"


async def payment_world(db):
    accountant = await make_user(db, 2)
    payer = await make_user(db, USER_ID, Role.CLIENT, bot_blocked=True)
    company = await make_company(db, accountant, short_name="Ромашка")
    await link_client(db, company, payer, can_mark_paid=True)
    task = Task(
        company_id=company.id,
        source="custom",
        kind="payment",
        title="Налог",
        due_date=today(),
        original_due_date=today(),
        client_visible=True,
    )
    db.add(task)
    await db.commit()
    return accountant, payer, task.id


async def task_status(db, task_id: int) -> str:
    return await db.scalar(select(Task.status).where(Task.id == task_id))


async def test_paid_button_and_cancel_by_accountant(chat, db):
    accountant, _, task_id = await payment_world(db)

    await chat.press(f"paid:{task_id}")
    assert await task_status(db, task_id) == "paid"
    assert MARKED in chat.telegram.edited[-1]
    await chat.press(f"paid:{task_id}")
    assert "уже изменён" in chat.telegram.answers[-1]

    await chat.press(f"unpaid:{task_id}", user_id=accountant.telegram_id)
    assert await task_status(db, task_id) == "planned"
    assert UNMARKED in chat.telegram.edited[-1]


@pytest.mark.parametrize("data", ["paid:999", "paid:x", "unpaid:1"])
async def test_forged_buttons(chat, db, data):
    _, _, task_id = await payment_world(db)

    await chat.press(data, user_id=777)

    assert await task_status(db, task_id) == "planned"
    assert chat.telegram.answers[-1] == ACCESS_BY_INVITE


async def test_today_and_week_commands(chat, db):
    accountant, payer, task_id = await payment_world(db)

    for user in (accountant, payer):
        reply = await chat.command("/today", user.telegram_id)
        assert "Ромашка: Налог" in reply
    assert await chat.command("/week", 999) == ACCESS_BY_INVITE
    stranger = await make_user(db, 888, Role.ACCOUNTANT)
    assert await chat.command("/week", stranger.telegram_id) == NOTHING


async def test_block_and_unblock(chat, db):
    _, payer, _ = await payment_world(db)

    await chat.command("/today", payer.telegram_id)
    await chat.start()
    assert (await users(db))[USER_ID].bot_blocked is False
    await chat.membership("kicked")
    assert (await users(db))[USER_ID].bot_blocked is True
    await chat.membership("member")
    assert (await users(db))[USER_ID].bot_blocked is False
