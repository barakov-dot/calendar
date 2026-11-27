"""Отчёт о выполненном. Сотрудникам, в пределах доступных им компаний."""

import asyncio
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict

from app.api.companies import NOT_FOUND
from app.api.deps import Database
from app.api.reminders import Reader
from app.core.permissions import get_accessible_company
from app.models import User
from app.services import reports, tasks
from app.services.telegram.documents import SendError, send_document

router = APIRouter(prefix="/reports")

MAX_PERIOD = timedelta(days=3 * 366)
FORMATS = {
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        reports.to_xlsx,
    ),
    "pdf": ("application/pdf", reports.to_pdf),
}


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date_from: date
    date_to: date
    company_id: int | None = None
    accountant_id: int | None = None


class SummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    accountant: str
    company: str
    on_time: int
    late: int
    not_required: int
    overdue: int
    paid_kopecks: int


class ReportOut(BaseModel):
    summary: list[SummaryOut]
    tasks: int


def period(
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
    company_id: int | None = None,
    accountant_id: int | None = None,
) -> Period:
    return Period(
        date_from=date_from, date_to=date_to, company_id=company_id, accountant_id=accountant_id
    )


Asked = Annotated[Period, Depends(period)]


async def _build(db: Database, user: User, asked: Period) -> reports.Report:
    if not timedelta(0) <= asked.date_to - asked.date_from <= MAX_PERIOD:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Конец периода должен быть не раньше начала, период — не больше трёх лет",
        )
    if asked.company_id is not None:
        if await get_accessible_company(db, user, asked.company_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return await reports.build(db, user, current=tasks.today(), **asked.model_dump())


@router.get("/completed")
async def preview(asked: Asked, user: Reader, db: Database) -> ReportOut:
    report = await _build(db, user, asked)
    return ReportOut(
        summary=[SummaryOut.model_validate(row) for row in report.summary],
        tasks=len(report.rows),
    )


@router.get("/completed.{extension}")
async def download(
    extension: Literal["xlsx", "pdf"], asked: Asked, user: Reader, db: Database
) -> Response:
    report = await _build(db, user, asked)
    media_type, render = FORMATS[extension]
    return Response(
        # сборка файла занимает процессор: не в общем цикле запросов
        await asyncio.to_thread(render, report),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{report.filename(extension)}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/completed.{extension}/send", status_code=status.HTTP_204_NO_CONTENT)
async def send(
    extension: Literal["xlsx", "pdf"], asked: Asked, user: Reader, db: Database
) -> Response:
    report = await _build(db, user, asked)
    render = FORMATS[extension][1]
    try:
        data = await asyncio.to_thread(render, report)
        await send_document(user, data, report.filename(extension), report.title)
    except SendError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
