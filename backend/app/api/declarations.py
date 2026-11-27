"""Загрузка декларации: сначала показывается, что изменится, затем суммы записываются.

Файл передаётся телом запроса и нигде не сохраняется. Доступно администратору и
бухгалтеру по своим организациям.
"""

from datetime import date

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.api.companies import Staff
from app.api.deps import Database
from app.services.declarations import apply as declarations
from app.services.declarations.parser import MAX_BYTES, DeclarationError, parse

router = APIRouter(prefix="/declarations")


class PartOut(BaseModel):
    # пусто — платежа ещё нет, он появится при записи
    task_id: int | None
    title: str
    due_date: date
    current_kopecks: int | None
    new_kopecks: int
    # почему сумма не меняется; пусто — меняется
    kept: str


class TotalOut(BaseModel):
    label: str
    kopecks: int


class DeclarationOut(BaseModel):
    company_id: int
    company_name: str
    inn: str
    title: str
    correction: int
    totals: list[TotalOut]
    parts: list[PartOut]
    warnings: list[str]
    # при записи организация перейдёт на ежемесячные авансы по прибыли
    switches_to_monthly: bool


async def _body(request: Request) -> bytes:
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_BYTES:
            break  # разбор откажет с понятным объяснением
    return bytes(data)


def _out(found: declarations.Plan) -> DeclarationOut:
    source, company = found.declaration, found.company
    return DeclarationOut(
        company_id=company.id,
        company_name=company.short_name or company.name,
        inn=source.inn,
        title=source.title,
        correction=source.correction,
        totals=[TotalOut(label=label, kopecks=kopecks) for label, kopecks in source.totals],
        warnings=list(source.warnings),
        switches_to_monthly=found.switches_to_monthly,
        parts=[
            PartOut(
                task_id=None if part.created else part.task.id,
                title=part.task.title,
                due_date=part.task.due_date,
                current_kopecks=part.task.amount_kopecks,
                new_kopecks=part.new_kopecks,
                kept=part.kept,
            )
            for part in found.parts
        ],
    )


async def _plan(
    request: Request, user: Staff, db: Database, lock: bool = False
) -> declarations.Plan:
    try:
        return await declarations.plan(db, user, parse(await _body(request)), lock)
    except DeclarationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None


@router.post("/preview")
async def preview(request: Request, user: Staff, db: Database) -> DeclarationOut:
    found = _out(await _plan(request, user, db))
    # предпросмотр ничего не сохраняет, даже смену порядка авансов
    await db.rollback()
    return found


@router.post("/apply")
async def apply(request: Request, user: Staff, db: Database) -> DeclarationOut:
    """Отвечает тем, как было до записи: current_kopecks — прежние суммы."""
    found = await _plan(request, user, db, lock=True)
    # снимок прежних сумм делается до записи: она меняет те же объекты
    before = _out(found)
    await declarations.apply(db, user, found)
    return before
