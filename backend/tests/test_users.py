from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_config
from app.core.settings_store import get_store
from app.models import AuditLog, Notification, Role, Substitution, User
from app.services import invites
from app.services.notify.sender import deliver
from app.services.telegram.factory import create_bot
from tests.factories import auth, link_client, make_company, make_user
from tests.fakes import FakeTelegram

pytestmark = pytest.mark.usefixtures("secrets")


@pytest.fixture
async def world(db):
    admin = await make_user(db, 1, Role.ADMIN, first_name="Анна")
    accountant = await make_user(db, 2, first_name="Борис", last_name="Иванов", username="boris")
    helper = await make_user(db, 3, Role.ASSISTANT, first_name="Дина")
    client_user = await make_user(db, 4, Role.CLIENT, first_name="Пётр")
    silent = await make_user(db, 5, Role.CLIENT, first_name="Олег", bot_blocked=True)
    off = await make_user(db, 6, Role.CLIENT, first_name="Яна", is_active=False)
    company = await make_company(db, accountant, short_name="ООО «Ромашка»")
    await link_client(db, company, client_user, can_mark_paid=True, is_primary=True)
    return locals()


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("GET", "/api/admin/users", None),
        ("GET", "/api/admin/users/1", None),
        ("PATCH", "/api/admin/users/1", {"first_name": "Х"}),
        ("GET", "/api/admin/broadcasts", None),
        ("GET", "/api/admin/broadcasts/1/deliveries", None),
        ("POST", "/api/admin/broadcasts/preview", {"roles": ["client"]}),
        ("POST", "/api/admin/broadcasts", {"roles": ["client"], "text": "т"}),
    ],
)
async def test_only_admin(client, db, method, url, body):
    assert (await client.request(method, url, json=body)).status_code == 401
    roles = (Role.ACCOUNTANT, Role.ASSISTANT, Role.CLIENT)
    for number, role in enumerate(roles, start=10):
        user = await make_user(db, number, role)
        response = await client.request(method, url, json=body, headers=auth(user))
        assert response.status_code == 403


async def listed(client, world, **params) -> list[dict]:
    response = await client.get("/api/admin/users", params=params, headers=auth(world["admin"]))
    assert response.status_code == 200, response.json()
    return response.json()


async def test_list_all_with_filter_and_search(client, world):
    everyone = await listed(client, world)

    assert [item["first_name"] for item in everyone] == [
        "Анна",
        "Борис",
        "Дина",
        "Олег",
        "Пётр",
        "Яна",
    ]
    counts = {item["first_name"]: item["companies_count"] for item in everyone}
    assert (counts["Борис"], counts["Пётр"], counts["Дина"]) == (1, 1, 0)
    assert "telegram_id" not in everyone[0]
    clients = await listed(client, world, role="client")
    assert {item["first_name"] for item in clients} == {"Олег", "Пётр", "Яна"}
    for query in ("борис ива", "@boris"):
        assert [item["first_name"] for item in await listed(client, world, q=query)] == ["Борис"]
    assert await listed(client, world, q="%") == []


async def test_cards_of_accountant_and_client(client, db, world):
    db.add(
        Substitution(
            accountant_id=world["accountant"].id,
            substitute_id=world["admin"].id,
            date_from=datetime.now(UTC).date(),
            date_to=datetime.now(UTC).date() + timedelta(days=5),
            created_by=world["admin"].id,
        )
    )
    await db.commit()
    headers = auth(world["admin"])

    accountant = await client.get(f"/api/admin/users/{world['accountant'].id}", headers=headers)
    payer = await client.get(f"/api/admin/users/{world['client_user'].id}", headers=headers)
    missing = await client.get("/api/admin/users/999", headers=headers)

    assert accountant.json()["telegram_id"] == 2
    assert [item["name"] for item in accountant.json()["companies"]] == ["ООО «Ромашка»"]
    assert accountant.json()["substitutions"][0]["substitute_name"] == "Анна"
    company = payer.json()["companies"][0]
    assert (company["can_mark_paid"], company["receive_reminders"]) == (True, True)
    assert missing.status_code == 404


async def patch(client, world, user, **body):
    return await client.patch(
        f"/api/admin/users/{user.id}", json=body, headers=auth(world["admin"])
    )


async def test_name_set_by_admin_survives_telegram(client, db, world):
    user = world["client_user"]

    changed = await patch(client, world, user, first_name=" Пётр Ильич ", last_name="Смирнов")

    assert changed.json()["first_name"] == "Пётр Ильич"
    assert changed.json()["name_overridden"] is True
    await db.refresh(user)
    invites.apply_profile(user, invites.TelegramProfile(4, "Petya", "S", "petya"))
    assert (user.first_name, user.last_name, user.username) == ("Пётр Ильич", "Смирнов", "petya")
    await db.commit()

    reset = await patch(client, world, user, reset_name=True)

    assert reset.json()["name_overridden"] is False
    await db.refresh(user)
    invites.apply_profile(user, invites.TelegramProfile(4, "Petya", "S", "petya"))
    assert user.first_name == "Petya"
    journal = await db.scalars(select(AuditLog).where(AuditLog.action == "user.update"))
    assert "Смирнов" not in str([row.payload for row in journal])


async def test_unchanged_name_is_not_pinned(client, world):
    response = await patch(client, world, world["client_user"], first_name="Пётр", last_name="")

    assert response.json()["name_overridden"] is False


async def test_empty_name_is_rejected(client, world):
    response = await patch(client, world, world["client_user"], first_name="", last_name="")

    assert response.status_code == 422


async def test_access_is_switched_off_but_not_for_admin(client, db, world):
    user = world["client_user"]

    assert (await patch(client, world, user, is_active=False)).json()["is_active"] is False
    assert (await client.get("/api/tasks", headers=auth(user))).status_code == 401
    refused = await patch(client, world, world["admin"], is_active=False)

    assert refused.status_code == 422
    assert (await db.get(User, world["admin"].id, populate_existing=True)).is_active


async def post(client, world, url, **body):
    return await client.post(url, json=body, headers=auth(world["admin"]))


async def test_preview_names_who_will_not_get_the_message(client, world):
    preview = await post(client, world, "/api/admin/broadcasts/preview", roles=["client"])

    assert preview.json()["recipients"] == ["Пётр"]
    assert [(item["name"], item["reason"]) for item in preview.json()["unreachable"]] == [
        ("Олег", "заблокировал(а) бота")
    ]
    # себе — только поимённо
    admins = await post(client, world, "/api/admin/broadcasts/preview", roles=["admin"])
    assert admins.json()["recipients"] == []
    both = await post(
        client,
        world,
        "/api/admin/broadcasts/preview",
        roles=["client"],
        user_ids=[world["admin"].id, world["client_user"].id],
    )
    assert both.json()["recipients"] == ["Анна", "Пётр"]


@pytest.mark.parametrize(
    "body",
    [
        {"text": "Привет"},
        {"text": "   ", "roles": ["client"]},
        {"text": "x" * 3501, "roles": ["client"]},
        {"text": "Привет", "roles": ["boss"]},
        {"text": "Привет", "user_ids": [999]},
    ],
)
async def test_invalid_broadcast_is_not_queued(client, db, world, body):
    response = await post(client, world, "/api/admin/broadcasts", **body)

    assert response.status_code == 422
    assert await db.scalar(select(Notification)) is None


async def test_broadcast_is_delivered_as_plain_text(client, db, world):
    text = "Офис закрыт 31.12 <b>& точка</b>"
    headers = auth(world["admin"])

    for number in (1, 2):  # две рассылки в один день не мешают друг другу
        created = await post(
            client,
            world,
            "/api/admin/broadcasts",
            text=f"{text} {number}",
            roles=["accountant", "assistant", "client"],
        )
        assert created.status_code == 201, created.json()
        assert (created.json()["total"], created.json()["pending"]) == (3, 3)

    async with FakeTelegram() as telegram:
        bot = create_bot(get_config(), None, telegram.api("127.0.0.1"))
        telegram.failures[3] = (403, "Forbidden: bot was blocked by the user", {})
        await deliver(db, bot, get_store().get(), datetime.now(UTC), pause=0)
        await bot.session.close()

    assert sorted(telegram.sent) == [
        (2, f"{text} 1"),
        (2, f"{text} 2"),
        (4, f"{text} 1"),
        (4, f"{text} 2"),
    ]
    history = (await client.get("/api/admin/broadcasts", headers=headers)).json()
    assert [item["text"] for item in history] == [f"{text} 2", f"{text} 1"]
    first = history[1]
    # помощник заблокировал бота: первое сообщение не доставлено, второе пропущено
    assert (first["sent"], first["failed"], first["pending"]) == (2, 1, 0)
    assert history[0]["skipped"] == 1
    states = await client.get(f"/api/admin/broadcasts/{first['id']}/deliveries", headers=headers)
    assert {item["name"]: item["status"] for item in states.json()} == {
        "Борис Иванов": "sent",
        "Дина": "failed",
        "Пётр": "sent",
    }
