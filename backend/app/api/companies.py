"""Компании, патенты и клиенты компании.

Права проверяются в каждом запросе. Недоступная компания отвечает 404,
чтобы не раскрывать, что она существует.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select

from app.api.admin_users import InviteOut, invite_link_base, invite_out
from app.api.deps import CurrentUser, Database, ManagerUser, require_role
from app.core.permissions import get_accessible_company
from app.core.settings_store import get_settings
from app.models import EDITORS, MANAGERS, Company, CompanyMember, InviteKind, Patent, Role, User
from app.schemas.company import (
    ClientCompanyOut,
    ClientInviteIn,
    CompanyCreate,
    CompanyListItem,
    CompanyOut,
    CompanyPatch,
    MemberOut,
    MemberPatch,
    PartyOut,
    PatentIn,
    PatentOut,
    StaffIn,
    SuggestOut,
)
from app.services import audit, companies, invites
from app.services import tasks as task_service
from app.services.dadata.client import DadataError, cached_party, search

router = APIRouter()
logger = logging.getLogger(__name__)

Staff = Annotated[User, Depends(require_role(*EDITORS))]

NOT_FOUND = "Компания не найдена"


async def staff_company(company_id: int, user: Staff, db: Database) -> Company:
    """Компания, которую пользователь может редактировать."""
    company = await get_accessible_company(db, user, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return company


StaffCompany = Annotated[Company, Depends(staff_company)]


async def _regenerate(db: Database, company: Company) -> None:
    """Пересчитывает сроки после изменения компании. Её сохранение уже состоялось,
    поэтому ошибка пересчёта не отменяет его: ночная генерация повторит попытку."""
    company_id = company.id
    try:
        await task_service.regenerate_company(db, company_id)
    except Exception:
        logger.exception("Не удалось пересчитать задачи компании %s", company_id)
        await db.rollback()
    await db.refresh(company)


def _rejected(error: companies.CompanyError) -> HTTPException:
    code = (
        status.HTTP_409_CONFLICT
        if isinstance(error, companies.DuplicateInn)
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    return HTTPException(code, str(error))


@router.get("/companies")
async def list_companies(
    user: CurrentUser,
    db: Database,
    archived: bool = False,
    q: Annotated[str, Query(max_length=100)] = "",
) -> list[CompanyListItem] | list[ClientCompanyOut]:
    items = await companies.list_for(db, user, archived, q)
    if user.role == Role.CLIENT:
        return [ClientCompanyOut.model_validate(item, from_attributes=True) for item in items]
    return items


# Объявлен раньше /companies/{company_id}, иначе «suggest» считался бы идентификатором.
@router.get("/companies/suggest")
async def suggest(_: Staff, q: Annotated[str, Query(min_length=3, max_length=300)]) -> SuggestOut:
    dadata = get_settings().dadata
    if not dadata.enabled or not dadata.api_key:
        return SuggestOut(enabled=False)
    try:
        found = await search(q, dadata.api_key, dadata.timeout_seconds)
    except DadataError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from None
    return SuggestOut(enabled=True, suggestions=[PartyOut.model_validate(p) for p in found])


@router.post("/companies", status_code=status.HTTP_201_CREATED)
async def create_company(body: CompanyCreate, user: Staff, db: Database) -> CompanyOut:
    # Бухгалтер создаёт компанию только себе; выбирать сотрудников могут админ и главный.
    accountant_ids, assistant_ids = [user.id], []
    if user.role in MANAGERS:
        assistant_ids = body.assistant_ids
        if body.accountant_ids is not None:
            accountant_ids = body.accountant_ids
    try:
        if not accountant_ids:
            raise companies.CompanyError("Назначьте хотя бы одного бухгалтера")
        await companies.check_staff(db, set(accountant_ids) - {user.id}, set(assistant_ids))
        data = companies.validate(body.company)
        company = await companies.create(
            db, user, data, accountant_ids, assistant_ids, body.patents, cached_party(data.inn)
        )
    except companies.CompanyError as error:
        raise _rejected(error) from None
    await _regenerate(db, company)
    return await companies.details(db, company)


@router.get("/companies/{company_id}")
async def read_company(
    company_id: int, user: CurrentUser, db: Database
) -> CompanyOut | ClientCompanyOut:
    company = await get_accessible_company(db, user, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    if user.role == Role.CLIENT:
        return ClientCompanyOut.model_validate(company)
    return await companies.details(db, company)


@router.patch("/companies/{company_id}")
async def edit_company(
    body: CompanyPatch, company: StaffCompany, user: Staff, db: Database
) -> CompanyOut:
    try:
        await companies.edit(db, user, company, body.company, body.is_archived)
    except companies.CompanyError as error:
        raise _rejected(error) from None
    await _regenerate(db, company)
    return await companies.details(db, company)


@router.delete("/companies/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_company(company: StaffCompany, user: Staff, db: Database) -> Response:
    """Компания не удаляется, а переносится в архив."""
    await companies.edit(db, user, company, {}, True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/companies/{company_id}/refresh-dadata")
async def refresh_dadata(company: StaffCompany, user: Staff, db: Database) -> CompanyOut:
    dadata = get_settings().dadata
    if not dadata.enabled or not dadata.api_key:
        raise HTTPException(status.HTTP_409_CONFLICT, "DaData выключена или не задан API-ключ")
    try:
        found = await search(company.inn, dadata.api_key, dadata.timeout_seconds, use_cache=False)
    except DadataError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from None
    party = next((p for p in found if p.inn == company.inn), None)
    if party is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "DaData не нашла организацию с этим ИНН")
    try:
        await companies.refresh_from_dadata(db, user, company, party)
    except companies.CompanyError as error:
        raise _rejected(error) from None
    return await companies.details(db, company)


@router.post("/admin/companies/{company_id}/staff")
async def set_staff(company_id: int, body: StaffIn, admin: ManagerUser, db: Database) -> CompanyOut:
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    try:
        await companies.set_staff(db, admin, company, body.accountant_ids, body.assistant_ids)
    except companies.CompanyError as error:
        raise _rejected(error) from None
    return await companies.details(db, company)


# --- патенты ---


async def _patent(db: Database, company: Company, patent_id: int) -> Patent:
    patent = await db.get(Patent, patent_id)
    # Патент другой компании не должен быть доступен через свою.
    if patent is None or patent.company_id != company.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Патент не найден")
    return patent


@router.get("/companies/{company_id}/patents")
async def list_patents(company: StaffCompany, db: Database) -> list[PatentOut]:
    return (await companies.details(db, company)).patents


@router.post("/companies/{company_id}/patents", status_code=status.HTTP_201_CREATED)
async def add_patent(body: PatentIn, company: StaffCompany, user: Staff, db: Database) -> PatentOut:
    if company.entity_type != "ip":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Патенты бывают только у ИП")
    patent = Patent(company_id=company.id, **body.model_dump())
    db.add(patent)
    await db.flush()
    audit.record(db, user.id, "patent.create", "patent", patent.id, body.model_dump(mode="json"))
    await db.commit()
    await _regenerate(db, company)
    return PatentOut.model_validate(patent)


@router.patch("/companies/{company_id}/patents/{patent_id}")
async def edit_patent(
    patent_id: int, body: PatentIn, company: StaffCompany, user: Staff, db: Database
) -> PatentOut:
    patent = await _patent(db, company, patent_id)
    for key, value in body.model_dump().items():
        setattr(patent, key, value)
    audit.record(db, user.id, "patent.update", "patent", patent.id, body.model_dump(mode="json"))
    await db.commit()
    await _regenerate(db, company)
    return PatentOut.model_validate(patent)


@router.delete(
    "/companies/{company_id}/patents/{patent_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_patent(
    patent_id: int, company: StaffCompany, user: Staff, db: Database
) -> Response:
    patent = await _patent(db, company, patent_id)
    await db.delete(patent)
    audit.record(db, user.id, "patent.delete", "patent", patent_id, {"company_id": company.id})
    await db.commit()
    await _regenerate(db, company)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- клиенты компании ---


async def _member(db: Database, company: Company, user_id: int) -> CompanyMember:
    member = await db.get(CompanyMember, (company.id, user_id))
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Клиент не привязан к компании")
    return member


@router.patch("/companies/{company_id}/members/{user_id}")
async def edit_member(
    user_id: int, body: MemberPatch, company: StaffCompany, user: Staff, db: Database
) -> list[MemberOut]:
    member = await _member(db, company, user_id)
    changes = {}
    for key, value in body.model_dump(exclude_none=True).items():
        if getattr(member, key) != value:
            changes[key] = {"from": getattr(member, key), "to": value}
            setattr(member, key, value)
    if changes:
        audit.record(
            db,
            user.id,
            "member.update",
            "company",
            company.id,
            {"user_id": user_id, "changes": changes},
        )
        await db.commit()
    return await companies.list_members(db, company.id)


@router.delete("/companies/{company_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_member(user_id: int, company: StaffCompany, user: Staff, db: Database) -> Response:
    member = await _member(db, company, user_id)
    await db.delete(member)
    audit.record(db, user.id, "member.delete", "company", company.id, {"user_id": user_id})
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/companies/{company_id}/invites")
async def list_client_invites(
    _: ManagerUser, company: StaffCompany, db: Database
) -> list[InviteOut]:
    found = await invites.list_open(db, InviteKind.CLIENT, company.id)
    if not found:
        return []
    base = invite_link_base()
    return [invite_out(invite, base) for invite in found]


@router.post("/companies/{company_id}/invites", status_code=status.HTTP_201_CREATED)
async def invite_client(
    body: ClientInviteIn, user: ManagerUser, company: StaffCompany, db: Database
) -> InviteOut:
    if company.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "Компания в архиве")
    base = invite_link_base()  # до записи в базу: без ссылки приглашение бесполезно
    invite = await invites.create(
        db, InviteKind.CLIENT, user, company_id=company.id, can_mark_paid=body.can_mark_paid
    )
    return invite_out(invite, base)


@router.delete(
    "/companies/{company_id}/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def revoke_client_invite(
    invite_id: int, user: ManagerUser, company: StaffCompany, db: Database
) -> Response:
    ids = [invite.id for invite in await invites.list_open(db, InviteKind.CLIENT, company.id)]
    if invite_id not in ids or not await invites.revoke(db, invite_id, user):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Приглашение не найдено или уже не действует"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/staff")
async def staff(_: ManagerUser, db: Database) -> list[dict]:
    """Кого можно закрепить за компанией: действующие бухгалтеры всех уровней,
    администраторы и помощники."""
    users = await db.scalars(
        select(User)
        .where(User.role.in_((*EDITORS, Role.ASSISTANT)), User.is_active.is_(True))
        .order_by(User.id)
    )
    return [
        {"id": user.id, "name": companies.person_name(user), "role": user.role} for user in users
    ]
