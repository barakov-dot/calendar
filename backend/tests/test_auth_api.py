from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.core.config import get_config
from app.core.security import create_token
from app.core.settings_store import get_store
from app.main import create_app, lifespan
from app.models import Company, CompanyMember, LoginRequest, Patent, Role, Task, User
from app.seed_dev import DEV_COMPANIES, DEV_USERS, seed
from app.services import login
from app.services.inn import is_valid_inn
from app.services.users import ensure_admin
from tests.conftest import JWT_SECRET
from tests.factories import auth, make_user
from tests.fakes import signed_init_data

pytestmark = pytest.mark.usefixtures("secrets")


def webapp(telegram_id: int) -> dict:
    return {"init_data": signed_init_data(telegram_id, datetime.now(UTC))}


async def test_webapp_login_and_me(client, db):
    await make_user(db, 100, Role.ACCOUNTANT, first_name="Борис")

    tokens = (await client.post("/api/auth/telegram-webapp", json=webapp(100))).json()
    me = await client.get("/api/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})

    assert me.json()["first_name"] == "Борис"
    assert me.json()["role"] == "accountant"
    assert "telegram_id" not in me.json()


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        (None, "Доступ по приглашению"),
        ({"is_active": False}, "Доступ по приглашению"),
        ({"pd_consent_at": None}, "согласие"),
    ],
)
async def test_webapp_login_denied(client, db, fields, message):
    if fields is not None:
        await make_user(db, 100, **fields)

    response = await client.post("/api/auth/telegram-webapp", json=webapp(100))

    assert response.status_code == 403
    assert message in response.json()["detail"]


async def test_webapp_login_with_forged_data(client, db):
    await make_user(db, 100)

    response = await client.post(
        "/api/auth/telegram-webapp", json={"init_data": webapp(100)["init_data"] + "0"}
    )

    assert response.status_code == 401


async def test_login_unavailable_without_jwt_secret(client, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "short")
    get_config.cache_clear()

    response = await client.post("/api/auth/login-request")

    assert response.status_code == 503
    assert "JWT_SECRET" in response.json()["detail"]


async def test_protected_endpoint_requires_access_token(client, db):
    user = await make_user(db, 100)
    refresh = create_token(user.id, "refresh", JWT_SECRET)

    assert (await client.get("/api/me")).status_code == 401
    response = await client.get("/api/me", headers={"Authorization": f"Bearer {refresh}"})
    assert response.status_code == 401


async def test_deactivation_revokes_access_and_refresh_immediately(client, db):
    user = await make_user(db, 100)
    headers = auth(user)
    refresh = {"refresh_token": create_token(user.id, "refresh", JWT_SECRET)}
    assert (await client.get("/api/me", headers=headers)).status_code == 200
    assert (await client.post("/api/auth/refresh", json=refresh)).status_code == 200

    await db.execute(update(User).values(is_active=False))
    await db.commit()

    assert (await client.get("/api/me", headers=headers)).status_code == 401
    assert (await client.post("/api/auth/refresh", json=refresh)).status_code == 401


async def test_site_login_through_bot(client, db):
    get_store().update({"telegram": {"bot_username": "@some_bot"}})
    user = await make_user(db, 100)

    request = (await client.post("/api/auth/login-request")).json()
    assert request["deeplink"] == f"https://t.me/some_bot?start=login_{request['nonce']}"
    assert request["code"] == login.comparison_code(request["nonce"])
    url = f"/api/auth/poll/{request['nonce']}"
    assert (await client.get(url)).json() == {"status": "pending", "tokens": None}

    assert await login.confirm(db, request["nonce"], user.telegram_id) is True
    assert await login.confirm(db, request["nonce"], 999) is False  # уже подтверждён

    result = (await client.get(url)).json()
    assert result["status"] == "ok"
    assert result["tokens"]["access_token"]
    assert (await client.get(url)).status_code == 410  # одноразовый


async def test_login_request_expires(client, db):
    get_store().update({"telegram": {"bot_username": "some_bot"}})
    nonce = (await client.post("/api/auth/login-request")).json()["nonce"]
    await db.execute(
        update(LoginRequest).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db.commit()

    assert await login.confirm(db, nonce, 100) is False
    assert (await client.get(f"/api/auth/poll/{nonce}")).status_code == 410
    # просроченные удаляются при следующем запросе
    await client.post("/api/auth/login-request")
    assert nonce not in (await db.scalars(select(LoginRequest.nonce))).all()


async def test_login_request_limit(client, monkeypatch):
    get_store().update({"telegram": {"bot_username": "some_bot"}})
    monkeypatch.setattr(login, "MAX_PENDING", 2)

    codes = [(await client.post("/api/auth/login-request")).status_code for _ in range(3)]

    assert codes == [200, 200, 429]


async def test_login_request_needs_bot_name(client):
    assert (await client.post("/api/auth/login-request")).status_code == 503


async def test_dev_login(client, db):
    await seed(db)
    await seed(db)

    users = (await client.get("/api/auth/dev-users")).json()
    assert len(users) == len(DEV_USERS)
    companies = (await db.scalars(select(Company))).all()
    assert len(companies) == len(DEV_COMPANIES)
    assert {(c.entity_type, c.main_regime) for c in companies} >= {
        ("ooo", "osno"),
        ("ooo", "usn6"),
        ("ip", "ausn_income"),
    }
    assert all(is_valid_inn(c.inn) for c in companies)
    assert len((await db.scalars(select(Patent))).all()) == 1
    assert (await db.scalars(select(Task).limit(1))).first() is not None
    assert True in (await db.scalars(select(CompanyMember.can_mark_paid))).all()
    tokens = await client.post("/api/auth/dev-login", json={"user_id": users[0]["id"]})
    assert tokens.status_code == 200


async def test_dev_login_does_not_exist_in_prod(monkeypatch, db):
    await seed(db)
    monkeypatch.setenv("APP_ENV", "prod")
    get_config.cache_clear()
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/auth/dev-users")).status_code == 404
        response = await client.post("/api/auth/dev-login", json={"user_id": 1})
        assert response.status_code == 404
    assert not any("dev" in path for path in app.openapi()["paths"])


async def test_api_start_seeds_admin_once(monkeypatch, db):
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "4242")
    get_config.cache_clear()
    app = create_app()

    for _ in range(2):
        async with lifespan(app):
            pass

    [admin] = (await db.scalars(select(User))).all()
    assert (admin.telegram_id, admin.role, admin.pd_consent_at) == (4242, "admin", None)


async def test_ensure_admin_restores_role(db):
    await make_user(db, 4242, Role.CLIENT, is_active=False, first_name="Имя")

    await ensure_admin(db, 4242)

    db.expire_all()
    [admin] = (await db.scalars(select(User))).all()
    assert (admin.role, admin.is_active, admin.first_name) == ("admin", True, "Имя")
