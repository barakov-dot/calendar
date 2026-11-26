"""Загрузить производственный календарь года: python -m app.load_calendar 2027.

Читает data/calendar/<год>.json, заменяет год в базе и пересчитывает сроки.
"""

import asyncio
import sys
from pathlib import Path

from app.core.config import get_config
from app.core.db import get_engine, get_sessionmaker
from app.services import audit
from app.services.calendar.workdays import CalendarError, read_calendar_file, save_year
from app.services.tasks import regenerate_all


async def main(year: int) -> None:
    calendar = read_calendar_file(Path(get_config().data_path) / "calendar" / f"{year}.json")
    if calendar.year != year:
        raise CalendarError(f"в файле указан {calendar.year} год")
    async with get_sessionmaker()() as db:
        await save_year(db, calendar)
        audit.record(db, None, "calendar.upload", "calendar", year)
        await db.commit()
        result = await regenerate_all(db)
    await get_engine().dispose()
    print(f"Календарь {year} загружен. Задач создано: {result.created}, изменено: {result.updated}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        sys.exit("Использование: make calendar year=2027")
    try:
        asyncio.run(main(int(sys.argv[1])))
    except CalendarError as error:
        sys.exit(f"Календарь не загружен: {error}")
