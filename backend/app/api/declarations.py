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
    task_id: int
    part: int
    due_date: date
    current_kopecks: int | None
    new_kopecks: int
    # почему сумма не меняется; пусто — меняется
    kept: str


class DeclarationOut(BaseModel):
    company_id: int
    company_name: str
    inn: str
    year: int
    quarter: int
    correction: int
    total_kopecks: int
    parts: list[PartOut]
    warnings: list[str]


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
        year=source.year,
        quarter=source.quarter,
        correction=source.correction,
        total_kopecks=source.total_kopecks,
        warnings=list(source.warnings),
        parts=[
            PartOut(
                task_id=part.task.id,
                part=part.task.part,
                due_date=part.task.due_date,
                current_kopecks=part.task.amount_kopecks,
                new_kopecks=part.new_kopecks,
                kept=part.kept,
            )
            for part in found.parts
        ],
    )


async def _run(action, request: Request, user: Staff, db: Database) -> DeclarationOut:
    try:
        found = await action(db, user, parse(await _body(request)))
    except DeclarationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    return _out(found)


@router.post("/preview")
async def preview(request: Request, user: Staff, db: Database) -> DeclarationOut:
    return await _run(declarations.plan, request, user, db)


@router.post("/apply")
async def apply(request: Request, user: Staff, db: Database) -> DeclarationOut:
    """Отвечает тем, как было до записи: current_kopecks — прежние суммы."""
    try:
        found = await declarations.plan(db, user, parse(await _body(request)))
        # снимок прежних сумм делается до записи: она меняет те же объекты
        before = _out(found)
        await declarations.apply(db, user, found)
    except DeclarationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    return before
