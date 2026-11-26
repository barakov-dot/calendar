import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health
from app.core.config import Config, get_config
from app.core.logging import setup_logging
from app.core.settings_store import get_store

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        get_store().ensure_file()
    except OSError as error:
        logger.error(
            "Не удалось создать файл настроек: %s. Проверьте права на каталог config "
            "(APP_UID/APP_GID в .env)",
            error,
        )
    yield


def create_app(config: Config | None = None) -> FastAPI:
    config = config or get_config()
    setup_logging()
    # Документация API — только в разработке.
    app = FastAPI(
        title="Платёжный календарь",
        docs_url="/api/docs" if config.is_dev else None,
        redoc_url=None,
        lifespan=lifespan,
        openapi_url="/api/openapi.json" if config.is_dev else None,
    )
    app.include_router(health.router, prefix="/api")
    return app


app = create_app()
