import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import get_config
from app.core.db import get_engine, get_sessionmaker
from app.core.settings_store import get_store
from app.main import app
from app.models import Base
from tests.database import prepare_test_database
from tests.fakes import TOKEN

JWT_SECRET = "test-jwt-secret-0123456789-0123456789"


@pytest.fixture(scope="session")
def database_url():
    original = os.environ["DATABASE_URL"]
    url = prepare_test_database()
    os.environ["DATABASE_URL"] = url
    yield url
    os.environ["DATABASE_URL"] = original


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path, database_url):
    """Тесты не видят настоящие секреты, settings.json и базу разработчика."""
    for name in ("BOT_TOKEN", "TELEGRAM_PROXY_URL", "ADMIN_TELEGRAM_ID", "JWT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("SETTINGS_PATH", str(tmp_path / "config" / "settings.json"))
    get_config.cache_clear()
    get_store.cache_clear()
    yield
    get_config.cache_clear()
    get_store.cache_clear()


@pytest.fixture
def secrets(monkeypatch):
    """Тестовые BOT_TOKEN и JWT_SECRET."""
    monkeypatch.setenv("BOT_TOKEN", TOKEN)
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    get_config.cache_clear()


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def db():
    async with get_sessionmaker()() as session:
        yield session


@pytest.fixture(autouse=True)
async def clean_database(isolated_environment):
    """Пустые таблицы перед тестом. Пул не переиспользуется между event loop разных тестов."""
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    async with get_engine().begin() as connection:
        await connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield
    await get_engine().dispose()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
