"""Отдельная база для тестов: данные разработки не затрагиваются."""

import asyncio
import os
import subprocess
import sys

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


def prepare_test_database() -> str:
    """Пересоздаёт базу <имя>_test, применяет миграции и возвращает её URL."""
    url = make_url(os.environ["DATABASE_URL"])
    name = url.database if url.database.endswith("_test") else f"{url.database}_test"
    test_url = url.set(database=name).render_as_string(hide_password=False)

    async def recreate() -> None:
        engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
        async with engine.connect() as connection:
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            await connection.execute(text(f'CREATE DATABASE "{name}"'))
        await engine.dispose()

    asyncio.run(recreate())
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=os.environ | {"DATABASE_URL": test_url},
        check=True,
        capture_output=True,
    )
    return test_url
