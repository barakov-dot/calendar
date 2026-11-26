import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import get_engine, get_sessionmaker
from app.main import app


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
