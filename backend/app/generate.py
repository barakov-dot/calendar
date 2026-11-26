"""Перегенерировать задачи по всем компаниям: python -m app.generate (make gen)."""

import asyncio

from app.core.db import get_engine, get_sessionmaker
from app.services.tasks import regenerate_all


async def main() -> None:
    async with get_sessionmaker()() as db:
        result = await regenerate_all(db)
    await get_engine().dispose()
    print(
        f"Создано: {result.created}, обновлено: {result.updated}, удалено: {result.deleted}, "
        f"«не требуется»: {result.not_required}, возвращено: {result.restored}"
    )
    if result.missing_calendar_years:
        print(f"Нет производственного календаря на: {sorted(result.missing_calendar_years)}")
    if result.missing_rule_years:
        print(f"Нет файла правил на: {sorted(result.missing_rule_years)} — задачи не созданы")


if __name__ == "__main__":
    asyncio.run(main())
