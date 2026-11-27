"""Повторяющиеся напоминания: по компании или личные.

Читают сотрудники в пределах доступа, меняют администратор и бухгалтер.
"""

from datetime import timedelta
from itertools import islice
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import or_, select

from app.api.companies import NOT_FOUND, Staff
from app.api.deps import Database, require_role
from app.core.permissions import accessible_company_ids_query, get_accessible_company
from app.models import EDITORS, Audience, Company, RecurringReminder, Role, User
from app.schemas.task import ReminderIn, ReminderOut
from app.services import audit, reminders, tasks
from app.services.calendar.workdays import load_calendar
from app.services.companies import person_name

router = APIRouter()

Reader = Annotated[User, Depends(require_role(*EDITORS, Role.ASSISTANT))]

REMINDER_NOT_FOUND = "Напоминание не найдено"


def _visible(user: User):
    company = RecurringReminder.company_id.in_(accessible_company_ids_query(user))
    personal = RecurringReminder.company_id.is_(None)
    if user.role in (Role.CHIEF, Role.ACCOUNTANT):
        personal = personal & (RecurringReminder.created_by == user.id)
    return or_(company, personal)


def _can_edit(user: User, reminder: RecurringReminder) -> bool:
    if user.role == Role.ADMIN:
        return True
    if user.role not in (Role.CHIEF, Role.ACCOUNTANT):
        return False
    return reminder.company_id is not None or reminder.created_by == user.id


async def _out(db: Database, user: User, reminder: RecurringReminder) -> ReminderOut:
    company = (
        await db.get(Company, reminder.company_id) if reminder.company_id is not None else None
    )
    schedule = reminders.Schedule.from_rrule(reminder.rrule)
    calendar = await load_calendar(db)
    current = tasks.today()
    upcoming = reminders.occurrence_dates(
        schedule, reminder.dtstart, reminder.until, current, current + timedelta(days=800)
    )
    return ReminderOut(
        id=reminder.id,
        company_id=reminder.company_id,
        company_name=(company.short_name or company.name) if company else "Личное",
        created_by_name=person_name(await db.get(User, reminder.created_by)),
        title=reminder.title,
        description=reminder.description,
        kind=reminder.kind,
        schedule=schedule,
        dtstart=reminder.dtstart,
        until=reminder.until,
        shift_rule=reminder.shift_rule,
        audience=reminder.audience,
        is_active=reminder.is_active,
        next_dates=[
            reminders.shift(day, reminder.shift_rule, calendar) for day in islice(upcoming, 3)
        ],
        editable=_can_edit(user, reminder),
    )


def _values(body: ReminderIn) -> dict:
    if body.until is not None and body.until < body.dtstart:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Дата окончания раньше даты начала"
        )
    # личное напоминание клиенту не показывается
    audience = Audience.ACCOUNTANT if body.company_id is None else body.audience
    return body.model_dump(exclude={"schedule", "company_id", "audience"}) | {
        "rrule": body.schedule.to_rrule(),
        "audience": audience,
        "client_visible": audience != Audience.ACCOUNTANT,
    }


async def _editable(db: Database, user: User, reminder_id: int) -> RecurringReminder:
    reminder = await db.scalar(
        select(RecurringReminder).where(RecurringReminder.id == reminder_id, _visible(user))
    )
    if reminder is None or not _can_edit(user, reminder):
        raise HTTPException(status.HTTP_404_NOT_FOUND, REMINDER_NOT_FOUND)
    return reminder


def _journal(body: ReminderIn) -> dict:
    return body.model_dump(mode="json", exclude={"description"})


@router.get("/reminders")
async def list_reminders(
    user: Reader, db: Database, company_id: int | None = None, personal: bool = False
) -> list[ReminderOut]:
    query = select(RecurringReminder).where(_visible(user)).order_by(RecurringReminder.id)
    if company_id is not None:
        query = query.where(RecurringReminder.company_id == company_id)
    if personal:
        query = query.where(RecurringReminder.company_id.is_(None))
    return [await _out(db, user, reminder) for reminder in list(await db.scalars(query))]


@router.post("/reminders", status_code=status.HTTP_201_CREATED)
async def create_reminder(body: ReminderIn, user: Staff, db: Database) -> ReminderOut:
    if body.company_id is not None:
        company = await get_accessible_company(db, user, body.company_id)
        if company is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
        if company.is_archived:
            raise HTTPException(status.HTTP_409_CONFLICT, "Компания в архиве")
    reminder = RecurringReminder(company_id=body.company_id, created_by=user.id, **_values(body))
    db.add(reminder)
    await db.flush()
    await reminders.expand(db, reminder, await load_calendar(db), tasks.today())
    audit.record(db, user.id, "reminder.create", "reminder", reminder.id, _journal(body))
    await db.commit()
    return await _out(db, user, reminder)


@router.patch("/reminders/{reminder_id}")
async def update_reminder(
    reminder_id: int, body: ReminderIn, user: Staff, db: Database
) -> ReminderOut:
    """Заменяет напоминание. Будущие задачи, которые никто не менял, создаются заново."""
    reminder = await _editable(db, user, reminder_id)
    if body.company_id != reminder.company_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Перенести напоминание в другую компанию нельзя",
        )
    current = tasks.today()
    await reminders.drop_future(db, reminder, current)
    for name, value in _values(body).items():
        setattr(reminder, name, value)
    await db.flush()
    await reminders.expand(db, reminder, await load_calendar(db), current)
    audit.record(db, user.id, "reminder.update", "reminder", reminder.id, _journal(body))
    await db.commit()
    return await _out(db, user, reminder)


@router.delete("/reminders/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reminder(reminder_id: int, user: Staff, db: Database) -> Response:
    """Прошлые и изменённые задачи остаются, будущие нетронутые удаляются."""
    reminder = await _editable(db, user, reminder_id)
    await reminders.drop_future(db, reminder, tasks.today())
    await db.delete(reminder)
    audit.record(db, user.id, "reminder.delete", "reminder", reminder_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
