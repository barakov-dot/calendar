"""Производственный календарь. Только администратор."""

from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, status

from app.api.deps import AdminUser, Database
from app.services import audit
from app.services.calendar.workdays import CalendarError, loaded_years, parse_calendar, save_year
from app.services.tasks import regenerate_all

router = APIRouter(prefix="/admin/calendar")


@router.get("")
async def years(_: AdminUser, db: Database) -> list[dict]:
    return await loaded_years(db)


@router.post("/{year}")
async def upload(
    year: int, admin: AdminUser, db: Database, data: Annotated[dict[str, Any], Body()]
) -> dict:
    """Заменяет календарь года и пересчитывает сроки всех компаний."""
    try:
        calendar = parse_calendar(data)
        if calendar.year != year:
            raise CalendarError(f"в файле указан {calendar.year} год, а загружается {year}")
    except CalendarError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    await save_year(db, calendar)
    audit.record(db, admin.id, "calendar.upload", "calendar", year, data)
    await db.commit()
    result = await regenerate_all(db)
    return {"year": year, "tasks_updated": result.updated, "tasks_created": result.created}
