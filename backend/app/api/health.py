import asyncio
import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text

from app.core.config import Config, get_config
from app.core.db import get_engine
from app.services.monitoring import read_worker, worker_status_path
from app.services.telegram.status import read_status, status_path

logger = logging.getLogger(__name__)
router = APIRouter()

DB_TIMEOUT_SECONDS = 3


async def check_database() -> bool:
    try:
        async with asyncio.timeout(DB_TIMEOUT_SECONDS):
            async with get_engine().connect() as connection:
                await connection.execute(text("SELECT 1"))
    except Exception as error:
        # Только тип ошибки: в тексте может оказаться строка подключения.
        logger.error("База данных недоступна: %s", type(error).__name__)
        return False
    return True


@router.get("/health")
async def health(response: Response, database_ok: bool = Depends(check_database)) -> dict[str, str]:
    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "error", "database": "unavailable"}
    return {"status": "ok", "database": "ok"}


@router.get("/health/services")
def services(response: Response, config: Annotated[Config, Depends(get_config)]) -> dict[str, str]:
    """Для внешнего мониторинга: только состояния, без подробностей."""
    now = time.time()
    bot = read_status(status_path(config.settings_path), now)["state"]
    worker = "ok" if read_worker(worker_status_path(config.settings_path), now) else "down"
    if bot not in ("connected", "connecting") or worker != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"bot": bot, "worker": worker}
