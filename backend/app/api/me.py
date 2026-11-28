"""Личные настройки уведомлений и контакты. Каждый видит и меняет только своё."""

from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, Database
from app.core.permissions import accessible_company_ids_query, business_today
from app.core.settings_store import get_settings
from app.models import Company, CompanyStaff, NotificationSettings, Role, User
from app.services import substitutions
from app.services.companies import person_name

router = APIRouter(prefix="/me")

Offset = Annotated[int, Field(ge=1, le=365)]


class NotificationPreferences(BaseModel):
    """null в полях означает «как по умолчанию»."""

    model_config = ConfigDict(extra="forbid")

    offsets_days: list[Offset] | None = Field(None, max_length=10)
    on_due_day: bool | None = None
    daily_digest: bool = True
    digest_time: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class Defaults(BaseModel):
    offsets_days: list[int]
    on_due_day: bool
    digest_time: str


class PreferencesOut(NotificationPreferences):
    defaults: Defaults


class Contact(BaseModel):
    company: str
    accountant: str
    username: str
    # временно замещает ответственного бухгалтера
    substitute: bool = False


class ContactsOut(BaseModel):
    support_contact: str
    accountants: list[Contact]


def _out(row: NotificationSettings | None) -> PreferencesOut:
    defaults = get_settings().notifications
    own = {name: getattr(row, name) for name in NotificationPreferences.model_fields} if row else {}
    return PreferencesOut(
        **own,
        defaults=Defaults(
            offsets_days=defaults.default_client_offsets_days,
            on_due_day=defaults.remind_on_due_day,
            digest_time=defaults.digest_time,
        ),
    )


@router.get("/notification-settings")
async def read_preferences(user: CurrentUser, db: Database) -> PreferencesOut:
    return _out(await db.get(NotificationSettings, user.id))


@router.put("/notification-settings")
async def save_preferences(
    body: NotificationPreferences, user: CurrentUser, db: Database
) -> PreferencesOut:
    row = await db.get(NotificationSettings, user.id)
    if row is None:
        row = NotificationSettings(user_id=user.id)
        db.add(row)
    for name, value in body.model_dump().items():
        if name == "offsets_days" and value is not None:
            value = sorted(set(value), reverse=True)
        setattr(row, name, value)
    await db.commit()
    return _out(row)


@router.get("/contacts")
async def contacts(user: CurrentUser, db: Database) -> ContactsOut:
    """Поддержка и бухгалтеры компаний клиента."""
    accountants = []
    if user.role == Role.CLIENT:
        rows = await db.execute(
            select(Company, User)
            .join(CompanyStaff, CompanyStaff.company_id == Company.id)
            .join(User, User.id == CompanyStaff.user_id)
            .where(
                Company.id.in_(accessible_company_ids_query(user)),
                User.is_active.is_(True),
                User.role.in_(substitutions.STAFF),
            )
            .order_by(Company.id, User.id)
        )
        replaced = await substitutions.active(db, business_today())
        accountants = []
        for company, accountant in rows:
            name = company.short_name or company.name
            # пока бухгалтера замещают, клиенту показываем, к кому обращаться
            substitute_ids = replaced.get(accountant.id, [])
            people = [await db.get(User, user_id) for user_id in substitute_ids] or [accountant]
            accountants += [
                Contact(
                    company=name,
                    accountant=person_name(person),
                    username=person.username,
                    substitute=bool(substitute_ids),
                )
                for person in people
            ]
    return ContactsOut(
        support_contact=get_settings().company.support_contact, accountants=accountants
    )
