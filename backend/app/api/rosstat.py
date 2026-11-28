"""Формы Росстата: сотрудники смотрят, администратор настраивает.

Клиентам раздел недоступен. Недоступная компания отвечает 404.
"""

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, update

from app.api.companies import NOT_FOUND, Staff
from app.api.deps import AdminUser, Database, require_role
from app.core.permissions import get_accessible_company
from app.core.settings_store import get_settings
from app.models import EDITORS, Company, Role, RosstatForm, Task, User
from app.services import audit
from app.services.rosstat import client as rosstat
from app.services.rosstat.sync import refresh_company

router = APIRouter()

Employee = Annotated[User, Depends(require_role(*EDITORS, Role.ASSISTANT))]
# заведомо существующая организация для проверки связи: ПАО Сбербанк
CHECK_INN = "7707083893"


class FormOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    index: str
    name: str
    okud: str
    periodicity: str
    period: str
    deadline: str
    due_date: date | None
    comment: str
    task_id: int | None = None
    status: str | None = None


class CompanyForms(BaseModel):
    enabled: bool
    okpo: str
    checked_at: datetime | None
    error: str
    forms: list[FormOut]


class RosstatStatus(BaseModel):
    has_certificate: bool
    total: int
    checked: int
    failed: int
    # сообщения об ошибках и сколько организаций получили каждое
    errors: dict[str, int]


class CheckOut(BaseModel):
    ok: bool
    message: str


async def _company(db: Database, user: User, company_id: int) -> Company:
    company = await get_accessible_company(db, user, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return company


async def _forms(db: Database, company: Company) -> CompanyForms:
    rows = await db.execute(
        select(RosstatForm, Task)
        .outerjoin(Task, Task.rosstat_form_id == RosstatForm.id)
        .where(RosstatForm.company_id == company.id)
        .order_by(RosstatForm.due_date.nulls_last(), RosstatForm.index, RosstatForm.id)
    )
    forms = []
    for form, task in rows:
        out = FormOut.model_validate(form)
        if task is not None:
            out.task_id, out.status, out.due_date = task.id, task.status, task.due_date
        forms.append(out)
    return CompanyForms(
        enabled=get_settings().rosstat.enabled,
        okpo=company.rosstat_okpo,
        checked_at=company.rosstat_checked_at,
        error=company.rosstat_error,
        forms=forms,
    )


@router.get("/companies/{company_id}/rosstat")
async def company_forms(company_id: int, user: Employee, db: Database) -> CompanyForms:
    return await _forms(db, await _company(db, user, company_id))


@router.post("/companies/{company_id}/rosstat/refresh")
async def refresh(company_id: int, user: Staff, db: Database) -> CompanyForms:
    """Поиск прямо сейчас, не дожидаясь ночного."""
    company = await _company(db, user, company_id)
    if company.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "Компания в архиве")
    settings = get_settings().rosstat
    if not settings.enabled:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Поиск форм Росстата выключен в настройках сервиса"
        )
    try:
        async with rosstat.Client(settings.timeout_seconds) as client:
            await refresh_company(db, client, company)
    except rosstat.RosstatError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from None
    return await _forms(db, company)


@router.get("/admin/rosstat")
async def read_status(_: AdminUser, db: Database) -> RosstatStatus:
    active = Company.is_archived.is_(False)
    total = await db.scalar(select(func.count()).select_from(Company).where(active))
    checked = await db.scalar(
        select(func.count())
        .select_from(Company)
        .where(active, Company.rosstat_checked_at.is_not(None))
    )
    rows = await db.execute(
        select(Company.rosstat_error, func.count())
        .where(active, Company.rosstat_error != "")
        .group_by(Company.rosstat_error)
    )
    errors = {message: count for message, count in rows}
    return RosstatStatus(
        has_certificate=rosstat.certificate_path().is_file(),
        total=total,
        checked=checked,
        failed=sum(errors.values()),
        errors=errors,
    )


@router.post("/admin/rosstat/certificate", status_code=status.HTTP_204_NO_CONTENT)
async def upload_certificate(request: Request, admin: AdminUser, db: Database) -> Response:
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > rosstat.CERTIFICATE_MAX_BYTES:
            break
    try:
        rosstat.save_certificate(bytes(data))
    except rosstat.RosstatError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    audit.record(db, admin.id, "rosstat.certificate", "settings")
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/admin/rosstat/certificate", status_code=status.HTTP_204_NO_CONTENT)
async def delete_certificate(admin: AdminUser, db: Database) -> Response:
    rosstat.certificate_path().unlink(missing_ok=True)
    audit.record(db, admin.id, "rosstat.certificate_delete", "settings")
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/admin/rosstat/check")
async def check(_: AdminUser) -> CheckOut:
    """Пробный поиск: связь, сертификат и формат ответа."""
    try:
        async with rosstat.Client(get_settings().rosstat.timeout_seconds) as client:
            found = await client.organization(CHECK_INN)
            if found is None:
                return CheckOut(ok=False, message="Росстат не нашёл проверочную организацию")
            forms = await client.forms(found["id"])
    except rosstat.RosstatError as error:
        return CheckOut(ok=False, message=str(error))
    return CheckOut(
        ok=True, message=f"Связь есть, получено форм проверочной организации: {len(forms)}"
    )


@router.post("/admin/rosstat/run", status_code=status.HTTP_204_NO_CONTENT)
async def run_all(admin: AdminUser, db: Database) -> Response:
    """Ставит все организации в очередь: воркер обойдёт их в течение нескольких минут."""
    await db.execute(update(Company).values(rosstat_checked_at=None))
    audit.record(db, admin.id, "rosstat.run", "settings")
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
