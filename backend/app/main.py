from fastapi import FastAPI

from app.api import health
from app.core.config import Config, get_config
from app.core.logging import setup_logging


def create_app(config: Config | None = None) -> FastAPI:
    config = config or get_config()
    setup_logging()
    # Документация API — только в разработке.
    app = FastAPI(
        title="Платёжный календарь",
        docs_url="/api/docs" if config.is_dev else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if config.is_dev else None,
    )
    app.include_router(health.router, prefix="/api")
    return app


app = create_app()
