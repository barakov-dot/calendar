"""Операции с компаниями. Права проверяет вызывающий через core.permissions."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import accessible_company_ids_query
from app.core.settings_store import get_settings
from app.models import (
    EDITORS,
    Company,
    CompanyMember,
    CompanyStaff,
    Invite,
    Patent,
    Role,
    Signature,
    Task,
    TaskStatus,
    User,
)
from app.schemas.company import (
    CompanyData,
    CompanyListItem,
    CompanyOut,
    MemberOut,
    PatentIn,
    PatentOut,
    StaffOut,
)
from app.services import audit, staff
from app.services.dadata.client import Party
from app.services.task_state import before_start_condition

# Поля карточки, которые приходят из DaData и обновляются кнопкой «Обновить».
DADATA_FIELDS = (
    "kpp",
    "ogrn",
    "registration_date",
    "name",
    "short_name",
    "address",
    "okved",
    "director_name",
)
# Значения этих полей в журнал не пишутся: там могут быть персональные данные.
NOT_JOURNALED = {"notes", "director_name", "address"}
MISSING_AMOUNT_AHEAD = timedelta(days=30)


class CompanyError(Exception):
    """Операция невозможна. Текст показывается пользователю."""


class DuplicateInn(CompanyError):
    pass


def validate(data: dict) -> CompanyData:
    try:
        return CompanyData.model_validate(data)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(map(str, item['loc'])) or 'компания'}: "
            f"{item['msg'].removeprefix('Value error, ')}"
            for item in error.errors(include_input=False, include_url=False)
        )
        raise CompanyError(problems) from None


def person_name(user: User | None) -> str:
    if user is None:
        return ""
    name = f"{user.first_name} {user.last_name}".strip()
    return name or (f"@{user.username}" if user.username else "Без имени")


async def check_staff(db: AsyncSession, accountant_ids: set[int], assistant_ids: set[int]) -> None:
    """Кого можно закрепить за компанией."""
    groups = (
        (accountant_ids, EDITORS, "Бухгалтером может быть только действующий бухгалтер"),
        (assistant_ids, (Role.ASSISTANT,), "Помощником может быть только действующий помощник"),
    )
    for ids, roles, message in groups:
        for user_id in sorted(ids):
            user = await db.get(User, user_id)
            if user is None or not user.is_active or user.role not in roles:
                raise CompanyError(message)


async def create(
    db: AsyncSession,
    actor: User,
    data: CompanyData,
    accountant_ids: list[int],
    assistant_ids: list[int],
    patents: list[PatentIn],
    party: Party | None,
) -> Company:
    if patents and data.entity_type != "ip":
        raise CompanyError("Патенты бывают только у ИП")
    existing = await db.scalar(select(Company).where(Company.inn == data.inn))
    if existing is not None:
        archived = " (в архиве)" if existing.is_archived else ""
        raise DuplicateInn(
            f"Компания с этим ИНН уже есть{archived}. Если вы её не видите, "
            "обратитесь к администратору."
        )
    company = Company(**data.model_dump())
    if party is not None:
        company.dadata_raw = party.raw
        company.dadata_updated_at = datetime.now(UTC)
    db.add(company)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise DuplicateInn("Компания с этим ИНН уже есть") from None
    db.add_all(Patent(company_id=company.id, **patent.model_dump()) for patent in patents)
    members = sorted({*accountant_ids, *assistant_ids})
    db.add_all(CompanyStaff(company_id=company.id, user_id=user_id) for user_id in members)
    audit.record(
        db,
        actor.id,
        "company.create",
        "company",
        company.id,
        {"inn": company.inn, "staff": members, "patents": len(patents)},
    )
    await db.commit()
    return company


def _apply(company: Company, values: dict) -> dict:
    """Меняет поля и возвращает изменения для журнала."""
    changes = {}
    for key, value in values.items():
        if getattr(company, key) != value:
            setattr(company, key, value)
            journal = value.isoformat() if isinstance(value, date) else value
            changes[key] = None if key in NOT_JOURNALED else journal
    return changes


async def edit(
    db: AsyncSession, actor: User, company: Company, patch: dict, is_archived: bool | None
) -> None:
    current = {name: getattr(company, name) for name in CompanyData.model_fields}
    data = validate(current | patch)
    if data.entity_type != "ip" and await db.scalar(
        select(func.count()).select_from(Patent).where(Patent.company_id == company.id)
    ):
        raise CompanyError("Сначала удалите патенты: они бывают только у ИП")
    if data.inn != company.inn and await db.scalar(
        select(Company.id).where(Company.inn == data.inn)
    ):
        raise DuplicateInn("Компания с этим ИНН уже есть")
    values = data.model_dump()
    if is_archived is not None:
        values["is_archived"] = is_archived
    changes = _apply(company, values)
    if changes:
        audit.record(db, actor.id, "company.update", "company", company.id, {"changes": changes})
        await db.commit()


async def refresh_from_dadata(
    db: AsyncSession, actor: User, company: Company, party: Party
) -> None:
    """Обновляет реквизиты. Налоговые параметры и заметки не трогает."""
    current = {name: getattr(company, name) for name in CompanyData.model_fields}
    fresh = {name: getattr(party, name) for name in DADATA_FIELDS if getattr(party, name)}
    data = validate(current | fresh | {"region_code": party.region_code})
    changes = _apply(company, data.model_dump())
    company.dadata_raw = party.raw
    company.dadata_updated_at = datetime.now(UTC)
    audit.record(db, actor.id, "company.dadata", "company", company.id, {"changes": changes})
    await db.commit()


async def set_staff(
    db: AsyncSession,
    actor: User,
    company: Company,
    accountant_ids: list[int],
    assistant_ids: list[int],
) -> None:
    """Заменяет список сотрудников компании."""
    previous = set(
        await db.scalars(select(CompanyStaff.user_id).where(CompanyStaff.company_id == company.id))
    )
    wanted = {*accountant_ids, *assistant_ids}
    # уже назначенных не перепроверяем: отключённый сотрудник не мешает менять остальных
    await check_staff(db, set(accountant_ids) - previous, set(assistant_ids) - previous)
    if wanted == previous:
        return
    removed = previous - wanted
    await db.execute(
        delete(CompanyStaff).where(
            CompanyStaff.company_id == company.id, CompanyStaff.user_id.in_(removed)
        )
    )
    db.add_all(
        CompanyStaff(company_id=company.id, user_id=user_id) for user_id in wanted - previous
    )
    # ссылки, выданные снятыми сотрудниками, перестают действовать
    await db.execute(
        update(Invite)
        .where(
            Invite.company_id == company.id,
            Invite.created_by.in_(removed),
            Invite.used_at.is_(None),
            Invite.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    audit.record(
        db,
        actor.id,
        "company.staff",
        "company",
        company.id,
        {"added": sorted(wanted - previous), "removed": sorted(removed)},
    )
    await db.commit()


def _names(users: list[User]) -> str:
    return ", ".join(person_name(user) for user in users)


def _member(user: User) -> StaffOut:
    return StaffOut(id=user.id, name=person_name(user), is_active=user.is_active)


async def list_for(
    db: AsyncSession, user: User, archived: bool, search: str
) -> list[CompanyListItem]:
    patents = (
        select(func.count())
        .where(Patent.company_id == Company.id)
        .correlate(Company)
        .scalar_subquery()
    )
    members = (
        select(func.count())
        .where(CompanyMember.company_id == Company.id)
        .correlate(Company)
        .scalar_subquery()
    )
    blocked = (
        select(CompanyMember.user_id)
        .join(User, User.id == CompanyMember.user_id)
        .where(CompanyMember.company_id == Company.id, User.bot_blocked.is_(True))
        .correlate(Company)
        .exists()
    )
    current = datetime.now(ZoneInfo(get_settings().company.timezone)).date()
    missing = (
        select(Task.id)
        .where(
            Task.company_id == Company.id,
            Task.status == TaskStatus.PLANNED,
            Task.needs_amount.is_(True),
            Task.amount_kopecks.is_(None),
            ~before_start_condition(),
            Task.due_date.between(current, current + MISSING_AMOUNT_AHEAD),
        )
        .correlate(Company)
        .exists()
    )
    signed = select(Signature.id).where(Signature.company_id == Company.id).correlate(Company)
    query = (
        select(Company, patents, members, blocked, missing, signed.exists())
        .where(
            Company.id.in_(accessible_company_ids_query(user)),
            Company.is_archived.is_(archived),
        )
        .order_by(func.lower(func.coalesce(func.nullif(Company.short_name, ""), Company.name)))
    )
    if search := search.strip():
        query = query.where(
            or_(
                Company.name.icontains(search, autoescape=True),
                Company.short_name.icontains(search, autoescape=True),
                Company.inn.startswith(search, autoescape=True),
            )
        )
    rows = (await db.execute(query)).all()
    found = await staff.teams(db, CompanyStaff.company_id.in_([row[0].id for row in rows]))
    return [
        CompanyListItem(
            **{
                name: getattr(company, name)
                for name in CompanyListItem.model_fields
                if hasattr(company, name)
            },
            accountant_name=_names(found.get(company.id, staff.Team()).accountants),
            patents_count=patent_count,
            members_count=member_count,
            has_blocked_member=has_blocked,
            has_missing_amount=has_missing,
            has_signature=has_signature,
        )
        for (
            company,
            patent_count,
            member_count,
            has_blocked,
            has_missing,
            has_signature,
        ) in rows
    ]


async def list_members(db: AsyncSession, company_id: int) -> list[MemberOut]:
    rows = await db.execute(
        select(CompanyMember, User)
        .join(User, User.id == CompanyMember.user_id)
        .where(CompanyMember.company_id == company_id)
        .order_by(CompanyMember.created_at, User.id)
    )
    return [
        MemberOut(
            user_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
            is_primary=member.is_primary,
            can_mark_paid=member.can_mark_paid,
            receive_reminders=member.receive_reminders,
            bot_blocked=user.bot_blocked,
        )
        for member, user in rows
    ]


async def details(db: AsyncSession, company: Company) -> CompanyOut:
    patents = await db.scalars(
        select(Patent).where(Patent.company_id == company.id).order_by(Patent.date_start, Patent.id)
    )
    result = CompanyOut.model_validate(company)
    team = await staff.team(db, company.id)
    result.accountant_name = _names(team.accountants)
    result.accountants = [_member(user) for user in team.accountants]
    result.assistants = [_member(user) for user in team.assistants]
    result.patents = [PatentOut.model_validate(patent) for patent in patents]
    result.members = await list_members(db, company.id)
    return result
