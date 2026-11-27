import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api import (
    admin_calendar,
    admin_settings,
    admin_users,
    attachments,
    auth,
    companies,
    declarations,
    demands,
    dev,
    health,
    me,
    reminders,
    reports,
    signatures,
    site_icon,
    substitutions,
    tasks,
    users,
)
from app.core.config import Config, get_config
from app.core.db import get_sessionmaker
from app.core.logging import setup_logging
from app.core.settings_store import get_store
from app.services.calendar.workdays import CalendarError, load_missing_years
from app.services.users import ensure_admin

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
    if admin_id := get_config().admin_telegram_id:
        async with get_sessionmaker()() as db:
            await ensure_admin(db, admin_id)
    else:
        logger.warning("ADMIN_TELEGRAM_ID не задан: администратор не создан")
    try:
        async with get_sessionmaker()() as db:
            directory = Path(get_config().data_path) / "calendar"
            if added := await load_missing_years(db, directory):
                logger.info("Загружен производственный календарь: %s", added)
    except CalendarError as error:
        logger.error("Производственный календарь не загружен: %s", error)
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
    app.include_router(auth.router, prefix="/api")
    app.include_router(admin_users.router, prefix="/api")
    app.include_router(admin_settings.router, prefix="/api")
    app.include_router(companies.router, prefix="/api")
    app.include_router(tasks.router, prefix="/api")
    app.include_router(reminders.router, prefix="/api")
    app.include_router(me.router, prefix="/api")
    app.include_router(admin_calendar.router, prefix="/api")
    modules = (
        attachments,
        declarations,
        demands,
        reports,
        signatures,
        site_icon,
        substitutions,
        users,
    )
    for module in modules:
        app.include_router(module.router, prefix="/api")
    if config.is_dev:
        app.include_router(dev.router, prefix="/api")
    return app


app = create_app()
