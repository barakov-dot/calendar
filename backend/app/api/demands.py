"""Требования инспекции. Меняют администратор и бухгалтеры, смотрят ещё помощник и клиент.

Клиент видит требования только своих компаний, без комментария и задач. Недоступное
требование отвечает 404.
"""

import asyncio
from datetime import date, datetime
from typing import Annotated
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.companies import Staff
from app.api.deps import AdminUser, Database, require_role
from app.core.permissions import accessible_company_ids_query
from app.models import EDITORS, Company, Demand, DemandStep, Role, TaskStatus, User
from app.schemas.company import MAX_KOPECKS
from app.services import attachments
from app.services.companies import person_name
from app.services.demands import service, share
from app.services.demands.recognize import pdf_text, read
from app.services.demands.types import get_book
from app.services.telegram.documents import SendError, send_document

router = APIRouter(prefix="/demands")

Viewer = Annotated[User, Depends(require_role(*EDITORS, Role.ASSISTANT, Role.CLIENT))]
Employee = Annotated[User, Depends(require_role(*EDITORS, Role.ASSISTANT))]
Day = Annotated[date, Field(ge=date(2020, 1, 1), le=date(2100, 12, 31))]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TermsIn(Input):
    knd: str = Field("", pattern=r"^(\d{7})?$")
    doc_date: Day
    sent_date: Day | None = None
    receipt_date: Day | None = None
    response_workdays: int | None = Field(None, ge=1, le=60)
    response_date: Day | None = None


class DemandIn(TermsIn):
    company_id: int
    number: str = Field("", max_length=64)
    amount_kopecks: int | None = Field(None, ge=0, le=MAX_KOPECKS)
    note: str = Field("", max_length=5000)


class DemandCreate(DemandIn):
    receipt_done: bool = False


class KindOut(BaseModel):
    knd: str
    name: str
    action: str
    response_label: str
    response_workdays: int | None
    is_payment: bool
    due_on_upload: bool


class DatesOut(BaseModel):
    sent_date: date
    receipt_date: date
    response_date: date | None


class RecognizedOut(BaseModel):
    # False — текста в файле нет (скан или фото): поля заполняются вручную
    readable: bool
    company_id: int | None = None
    inn: str = ""
    knd: str = ""
    number: str = ""
    doc_date: date | None = None
    response_workdays: int | None = None
    response_date: date | None = None
    amount_kopecks: int | None = None
    note: str = ""


class StepOut(BaseModel):
    # клиенту задачи не отдаются
    task_id: int | None
    due_date: date
    status: str


class DemandOut(BaseModel):
    id: int
    company_id: int
    company_name: str
    knd: str
    name: str
    action: str
    is_payment: bool
    response_label: str
    number: str
    doc_date: date
    sent_date: date
    receipt_date: date
    receipt_set: bool
    response_workdays: int | None
    response_date: date
    response_set: bool
    amount_kopecks: int | None
    note: str
    filename: str
    content_type: str
    closed: bool
    receipt: StepOut | None
    response: StepOut | None


class RecipientOut(BaseModel):
    user_id: int
    name: str
    # client | accountant | assistant
    group: str
    # почему сообщение не дойдёт; пусто — получит
    reason: str | None
    # последняя отправка этому человеку
    status: str | None
    sent_at: datetime | None


class ShareIn(Input):
    user_ids: list[int] = Field(min_length=1, max_length=200)
    comment: str = Field("", max_length=share.COMMENT_LIMIT)


def _failed(error: service.DemandError) -> HTTPException:
    return HTTPException(error.code, str(error))


async def _out(db: Database, user: User, rows: list[tuple[Demand, Company]]) -> list[DemandOut]:
    client = user.role == Role.CLIENT
    book = get_book()
    tasks = await service.steps(db, [demand.id for demand, _ in rows])
    result = []
    for demand, company in rows:
        kind = book.kind(demand.knd)
        found = {
            step: tasks.get((demand.id, step)) for step in (DemandStep.RECEIPT, DemandStep.RESPONSE)
        }
        steps = {
            step: None
            if task is None
            else StepOut(
                task_id=None if client else task.id, due_date=task.due_date, status=task.status
            )
            for step, task in found.items()
        }
        response = steps[DemandStep.RESPONSE]
        fields = {
            name: getattr(demand, name) for name in DemandOut.model_fields if hasattr(Demand, name)
        }
        if client:
            # комментарий — рабочая заметка бухгалтера
            fields["note"] = ""
        result.append(
            DemandOut(
                **fields,
                company_name=company.short_name or company.name,
                name=kind.name,
                action=kind.action,
                is_payment=kind.task_kind == "payment",
                response_label=kind.response_label,
                closed=response is not None and response.status != TaskStatus.PLANNED,
                receipt=steps[DemandStep.RECEIPT],
                response=response,
            )
        )
    return result


async def _one(db: Database, user: User, demand_id: int) -> DemandOut:
    try:
        demand = await service.get(db, user, demand_id)
    except service.DemandError as error:
        raise _failed(error) from None
    company = await db.get(Company, demand.company_id)
    return (await _out(db, user, [(demand, company)]))[0]


async def _body(request: Request) -> bytes:
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > attachments.MAX_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Файл больше 10 МБ")
    return bytes(data)


@router.get("/types")
async def types(_: Employee) -> list[KindOut]:
    book = get_book()
    return [
        KindOut(
            knd=kind.knd,
            name=kind.name,
            action=kind.action,
            response_label=kind.response_label,
            response_workdays=kind.response_workdays,
            is_payment=kind.task_kind == "payment",
            due_on_upload=kind.due_on_upload,
        )
        for kind in [*book.types, book.other]
    ]


@router.post("/dates")
async def dates(body: TermsIn, _: Staff, db: Database) -> DatesOut:
    """Сроки по введённым датам — для формы, ничего не сохраняет."""
    found = await service.calculate(db, service.Terms(**body.model_dump()))
    return DatesOut(sent_date=found.sent, receipt_date=found.receipt, response_date=found.response)


@router.post("/recognize")
async def recognize(request: Request, user: Staff, db: Database) -> RecognizedOut:
    """Читает реквизиты из PDF. Файл здесь не сохраняется."""
    data = await _body(request)
    if attachments.detect_type(data) != "application/pdf":
        return RecognizedOut(readable=False)
    # разбор PDF занимает процессор и не должен задерживать другие запросы
    text = await asyncio.to_thread(pdf_text, data)
    if not text:
        return RecognizedOut(readable=False)
    found = read(text)
    company = await service.match_company(db, user, found)
    return RecognizedOut(
        readable=True,
        company_id=company.id if company else None,
        inn=company.inn if company else next(iter(found.inns), ""),
        knd=found.knd,
        number=found.number,
        doc_date=found.doc_date,
        response_workdays=found.response_workdays,
        response_date=found.response_date,
        amount_kopecks=found.amount_kopecks,
        note=found.note,
    )


@router.get("")
async def list_demands(
    user: Viewer, db: Database, company_id: int | None = None
) -> list[DemandOut]:
    """Все доступные требования или одной компании: ближайший срок сверху."""
    query = (
        select(Demand, Company)
        .join(Company, Company.id == Demand.company_id)
        .where(
            Demand.company_id.in_(accessible_company_ids_query(user)),
            Company.is_archived.is_(False),
        )
        .order_by(Demand.response_date, Demand.id)
    )
    if company_id is not None:
        query = query.where(Demand.company_id == company_id)
    rows = await db.execute(query)
    return await _out(db, user, [tuple(row) for row in rows])


@router.get("/{demand_id}")
async def read_demand(demand_id: int, user: Viewer, db: Database) -> DemandOut:
    return await _one(db, user, demand_id)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(body: DemandCreate, user: Staff, db: Database) -> DemandOut:
    values = body.model_dump(exclude={"receipt_done"})
    try:
        demand = await service.save(db, user, None, values, body.receipt_done)
    except service.DemandError as error:
        raise _failed(error) from None
    return await _one(db, user, demand.id)


@router.put("/{demand_id}")
async def update(demand_id: int, body: DemandIn, user: Staff, db: Database) -> DemandOut:
    try:
        demand = await service.get(db, user, demand_id, lock=True)
        await service.save(db, user, demand, body.model_dump())
    except service.DemandError as error:
        raise _failed(error) from None
    return await _one(db, user, demand_id)


@router.delete("/{demand_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(demand_id: int, user: AdminUser, db: Database) -> Response:
    """Удаляет только администратор: вместе с требованием пропадают сроки и документ."""
    try:
        demand = await service.get(db, user, demand_id, lock=True)
    except service.DemandError as error:
        raise _failed(error) from None
    await service.remove(db, user, demand)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{demand_id}/file")
async def upload(demand_id: int, request: Request, user: Staff, db: Database) -> DemandOut:
    try:
        # права проверяются до приёма файла
        await service.get(db, user, demand_id)
        data = await _body(request)
        demand = await service.get(db, user, demand_id, lock=True)
        name = unquote(request.headers.get("x-filename", ""))
        await service.put_file(db, user, demand, name, data)
    except service.DemandError as error:
        raise _failed(error) from None
    return await _one(db, user, demand_id)


@router.get("/{demand_id}/file")
async def download(demand_id: int, user: Viewer, db: Database) -> Response:
    try:
        demand = await service.read_file(db, user, demand_id)
    except service.DemandError as error:
        raise _failed(error) from None
    return Response(
        demand.data,
        media_type=demand.content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(demand.filename)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.post("/{demand_id}/file/send", status_code=status.HTTP_204_NO_CONTENT)
async def send(demand_id: int, user: Viewer, db: Database) -> Response:
    """Присылает файл тому, кто просит, в чат с ботом."""
    try:
        demand = await service.read_file(db, user, demand_id)
        await send_document(user, demand.data, demand.filename)
    except service.DemandError as error:
        raise _failed(error) from None
    except SendError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _recipients(db: Database, demand: Demand) -> list[RecipientOut]:
    return [
        RecipientOut(
            user_id=item.user.id,
            name=person_name(item.user),
            group=item.group,
            reason=item.reason,
            status=item.status,
            sent_at=item.sent_at,
        )
        for item in await share.recipients(db, demand)
    ]


@router.get("/{demand_id}/recipients")
async def recipients(demand_id: int, user: Staff, db: Database) -> list[RecipientOut]:
    """Кому можно отправить требование: клиенты и бухгалтер организации, помощники."""
    try:
        demand = await service.get(db, user, demand_id)
    except service.DemandError as error:
        raise _failed(error) from None
    return await _recipients(db, demand)


@router.post("/{demand_id}/share")
async def share_demand(
    demand_id: int, body: ShareIn, user: Staff, db: Database
) -> list[RecipientOut]:
    """Ставит в очередь бота сообщение с документом выбранным получателям."""
    try:
        demand = await service.get(db, user, demand_id, lock=True)
        await share.send(db, user, demand, set(body.user_ids), body.comment.strip())
    except service.DemandError as error:
        raise _failed(error) from None
    return await _recipients(db, demand)
