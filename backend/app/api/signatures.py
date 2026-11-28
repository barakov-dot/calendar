"""Электронные подписи компании. Читают сотрудники, меняют администратор и бухгалтер."""

from datetime import date

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.companies import Staff, StaffCompany
from app.api.deps import Database
from app.api.reminders import Reader
from app.core.permissions import get_accessible_company
from app.core.settings_store import get_settings
from app.models import Company, Signature
from app.schemas.company import Input
from app.services import signatures, tasks

router = APIRouter()

NOT_FOUND = "Подпись не найдена"


class SignatureIn(Input):
    holder: str = Field(min_length=1, max_length=200)
    expires_on: date = Field(ge=date(2020, 1, 1), le=date(2100, 1, 1))
    notify_client: bool = False


class SignatureRow(BaseModel):
    """Строка общего списка подписей."""

    id: int
    company_id: int
    company_name: str
    holder: str
    expires_on: date
    days_left: int


class SignatureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    holder: str
    expires_on: date
    notify_client: bool
    # отрицательное — срок уже прошёл
    days_left: int = 0


def _out(signature: Signature) -> SignatureOut:
    result = SignatureOut.model_validate(signature)
    result.days_left = (signature.expires_on - tasks.today()).days
    return result


async def _own(db: Database, company: Company, signature_id: int) -> Signature:
    signature = await db.get(Signature, signature_id)
    # подпись другой компании не должна быть доступна через свою
    if signature is None or signature.company_id != company.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return signature


def _active(company: Company) -> Company:
    if company.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "Компания в архиве")
    return company


@router.get("/signature-holders")
async def holders(_: Reader) -> list[str]:
    """На кого выпускают подписи: список задаётся в настройках."""
    return get_settings().company.signature_holders


@router.get("/signatures")
async def all_signatures(user: Reader, db: Database) -> list[SignatureRow]:
    """Подписи всех доступных действующих компаний: ближайший срок сверху."""
    current = tasks.today()
    return [
        SignatureRow(
            id=signature.id,
            company_id=company.id,
            company_name=company.short_name or company.name,
            holder=signature.holder,
            expires_on=signature.expires_on,
            days_left=(signature.expires_on - current).days,
        )
        for signature, company in await signatures.list_all(db, user)
    ]


@router.get("/companies/{company_id}/signatures")
async def list_signatures(company_id: int, user: Reader, db: Database) -> list[SignatureOut]:
    if await get_accessible_company(db, user, company_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Компания не найдена")
    return [_out(item) for item in await signatures.list_for(db, company_id)]


@router.post("/companies/{company_id}/signatures", status_code=status.HTTP_201_CREATED)
async def add_signature(
    body: SignatureIn, company: StaffCompany, user: Staff, db: Database
) -> SignatureOut:
    signature = Signature(company_id=_active(company).id)
    return _out(await signatures.save(db, user, signature, body.model_dump()))


@router.patch("/companies/{company_id}/signatures/{signature_id}")
async def edit_signature(
    signature_id: int, body: SignatureIn, company: StaffCompany, user: Staff, db: Database
) -> SignatureOut:
    signature = await _own(db, _active(company), signature_id)
    return _out(await signatures.save(db, user, signature, body.model_dump()))


@router.delete(
    "/companies/{company_id}/signatures/{signature_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_signature(
    signature_id: int, company: StaffCompany, user: Staff, db: Database
) -> Response:
    await signatures.remove(db, user, await _own(db, company, signature_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
