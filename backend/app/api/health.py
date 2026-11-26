import asyncio
import logging

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text

from app.core.db import get_engine

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
