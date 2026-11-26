"""Тестовые пользователи для разработки: python -m app.seed_dev (make seed-dev).

Компании появятся вместе с таблицами в Фазе 3.
"""

import asyncio
import sys
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_config
from app.core.db import get_engine, get_sessionmaker
from app.models import Role, User

# Отрицательные telegram_id не пересекаются с настоящими пользователями.
DEV_USERS = (
    (-1, Role.ADMIN, "Анна", "Админова"),
    (-2, Role.ACCOUNTANT, "Борис", "Бухгалтеров"),
    (-3, Role.ACCOUNTANT, "Вера", "Балансова"),
    (-4, Role.CLIENT, "Клиент", "Первый"),
    (-5, Role.CLIENT, "Клиент", "Второй"),
    (-6, Role.CLIENT, "Клиент", "Платит сам"),
)


async def seed(db: AsyncSession) -> None:
    for telegram_id, role, first_name, last_name in DEV_USERS:
        await db.execute(
            insert(User)
            .values(
                telegram_id=telegram_id,
                role=role,
                first_name=first_name,
                last_name=last_name,
                pd_consent_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(index_elements=[User.telegram_id])
        )
    await db.commit()


async def main() -> None:
    async with get_sessionmaker()() as db:
        await seed(db)
    await get_engine().dispose()


if __name__ == "__main__":
    if not get_config().is_dev:
        sys.exit("seed-dev доступен только при APP_ENV=dev")
    asyncio.run(main())
    print(f"Готово: {len(DEV_USERS)} тестовых пользователей")
