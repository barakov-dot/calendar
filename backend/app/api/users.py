"""Пользователи и рассылки. Только администратор."""

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.api.deps import AdminUser, Database
from app.models import Broadcast, Role, User
from app.services import broadcasts, people
from app.services.companies import person_name

router = APIRouter(prefix="/admin")

USER_NOT_FOUND = "Пользователь не найден"
Name = Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)]
# запас до предела Telegram в 4096 символов
Message = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=3500)]


class PersonOut(BaseModel):
    id: int
    first_name: str
    last_name: str
    username: str
    role: str
    is_active: bool
    # дал согласие в боте
    connected: bool
    bot_blocked: bool
    companies_count: int = 0


class PersonCompany(BaseModel):
    id: int
    name: str
    is_archived: bool
    # только для клиента
    is_primary: bool | None = None
    can_mark_paid: bool | None = None
    receive_reminders: bool | None = None


class PersonSubstitution(BaseModel):
    id: int
    accountant_name: str
    substitute_name: str
    date_from: date
    date_to: date


class PersonCard(PersonOut):
    telegram_id: int
    pd_consent_at: datetime | None
    created_at: datetime
    # имя задано администратором и не берётся из Telegram
    name_overridden: bool
    companies: list[PersonCompany]
    substitutions: list[PersonSubstitution]


class PersonPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: Name | None = None
    last_name: Name | None = None
    is_active: bool | None = None
    # снова брать имя из Telegram
    reset_name: bool = False


class Audience(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roles: list[Role] = Field(default_factory=list, max_length=4)
    user_ids: list[int] = Field(default_factory=list, max_length=1000)


class BroadcastIn(Audience):
    text: Message


class Unreachable(BaseModel):
    id: int
    name: str
    reason: str


class Preview(BaseModel):
    recipients: list[str]
    unreachable: list[Unreachable]


class BroadcastOut(BaseModel):
    id: int
    text: str
    roles: list[str]
    author_name: str
    created_at: datetime
    total: int
    sent: int
    pending: int
    failed: int
    skipped: int


class Delivery(BaseModel):
    id: int
    name: str
    status: str


def _person(user: User, companies_count: int = 0) -> dict:
    return {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "username": user.username,
        "role": user.role,
        "is_active": user.is_active,
        "connected": user.pd_consent_at is not None,
        "bot_blocked": user.bot_blocked,
        "companies_count": companies_count,
    }


async def _user(db: Database, user_id: int) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, USER_NOT_FOUND)
    return user


async def _card(db: Database, user: User) -> PersonCard:
    if user.role == Role.CLIENT:
        companies = [
            PersonCompany(
                id=company.id,
                name=company.short_name or company.name,
                is_archived=company.is_archived,
                is_primary=member.is_primary,
                can_mark_paid=member.can_mark_paid,
                receive_reminders=member.receive_reminders,
            )
            for company, member in await people.client_companies(db, user)
        ]
    else:
        companies = [
            PersonCompany(
                id=company.id,
                name=company.short_name or company.name,
                is_archived=company.is_archived,
            )
            for company in await people.accountant_companies(db, user)
        ]
    return PersonCard(
        **_person(user, sum(not company.is_archived for company in companies)),
        telegram_id=user.telegram_id,
        pd_consent_at=user.pd_consent_at,
        created_at=user.created_at,
        name_overridden=user.name_overridden,
        companies=companies,
        substitutions=[
            PersonSubstitution(
                id=item.id,
                accountant_name=accountant,
                substitute_name=substitute,
                date_from=item.date_from,
                date_to=item.date_to,
            )
            for item, accountant, substitute in await people.substitutions_of(db, user)
        ],
    )


@router.get("/users")
async def list_users(
    _: AdminUser,
    db: Database,
    role: Role | None = None,
    q: Annotated[str, Query(max_length=100)] = "",
) -> list[PersonOut]:
    return [PersonOut(**_person(user, total)) for user, total in await people.search(db, role, q)]


@router.get("/users/{user_id}")
async def read_user(user_id: int, _: AdminUser, db: Database) -> PersonCard:
    return await _card(db, await _user(db, user_id))


@router.patch("/users/{user_id}")
async def update_user(
    user_id: int, body: PersonPatch, admin: AdminUser, db: Database
) -> PersonCard:
    user = await _user(db, user_id)
    try:
        await people.update(db, admin, user, **body.model_dump())
    except people.PersonError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    return await _card(db, user)


@router.post("/broadcasts/preview")
async def preview(body: Audience, admin: AdminUser, db: Database) -> Preview:
    found = await broadcasts.recipients(db, admin, body.roles, body.user_ids)
    return Preview(
        recipients=[person_name(user) for user in found.ready],
        unreachable=[
            Unreachable(id=user.id, name=person_name(user), reason=reason)
            for user, reason in found.unreachable
        ],
    )


def _broadcast(item: Broadcast, author: str, counts: dict[str, int]) -> BroadcastOut:
    return BroadcastOut(
        id=item.id,
        text=item.text,
        roles=item.roles,
        author_name=author,
        created_at=item.created_at,
        total=sum(counts.values()),
        sent=counts.get("sent", 0),
        pending=counts.get("pending", 0),
        failed=counts.get("failed", 0),
        skipped=counts.get("skipped", 0),
    )


@router.get("/broadcasts")
async def list_broadcasts(_: AdminUser, db: Database) -> list[BroadcastOut]:
    return [_broadcast(*row) for row in await broadcasts.history(db)]


@router.get("/broadcasts/{broadcast_id}/deliveries")
async def list_deliveries(broadcast_id: int, _: AdminUser, db: Database) -> list[Delivery]:
    if await db.get(Broadcast, broadcast_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Рассылка не найдена")
    return [
        Delivery(id=user.id, name=person_name(user), status=state)
        for user, state in await broadcasts.deliveries(db, broadcast_id)
    ]


@router.post("/broadcasts", status_code=status.HTTP_201_CREATED)
async def send_broadcast(body: BroadcastIn, admin: AdminUser, db: Database) -> BroadcastOut:
    try:
        item = await broadcasts.create(db, admin, body.text, body.roles, body.user_ids)
    except broadcasts.BroadcastError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    queued = await broadcasts.deliveries(db, item.id)
    await db.refresh(item)
    return _broadcast(item, person_name(admin), {"pending": len(queued)})
