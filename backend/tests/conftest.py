import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_config
from app.core.db import get_engine, get_sessionmaker
from app.core.settings_store import get_store
from app.main import app


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    """Тесты не видят настоящий токен, прокси и settings.json из .env разработчика."""
    for name in ("BOT_TOKEN", "TELEGRAM_PROXY_URL", "ADMIN_TELEGRAM_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SETTINGS_PATH", str(tmp_path / "config" / "settings.json"))
    get_config.cache_clear()
    get_store.cache_clear()
    yield
    get_config.cache_clear()
    get_store.cache_clear()


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
async def reset_engine():
    """Каждый тест работает в своём event loop, поэтому пул соединений не переиспользуется."""
    yield
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
