"""Задачи: списки, изменение, массовые действия, свои задачи, разбивка НДС.

Права проверяются в каждом запросе. Недоступная задача отвечает 404.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.companies import NOT_FOUND, Staff
from app.api.deps import CurrentUser, Database
from app.core.permissions import get_accessible_company
from app.core.settings_store import get_settings
from app.models import Task, TaskKind, TaskStatus, User
from app.schemas.company import MAX_KOPECKS
from app.schemas.task import (
    BulkIn,
    BulkOut,
    ClientTaskOut,
    NdsPart,
    TaskCreate,
    TaskDetail,
    TaskList,
    TaskPatch,
)
from app.services import payments, task_actions, tasks

router = APIRouter()

TASK_NOT_FOUND = "Задача не найдена"


class NdsAmountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_kopecks: int = Field(ge=0, le=MAX_KOPECKS)


def _show_notices() -> bool:
    return get_settings().tasks.show_notices_to_clients


def _rejected(error: task_actions.TaskError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))


async def _editable(db: Database, user: Staff, task_id: int) -> Task:
    found = await task_actions.editable(db, user, {task_id})
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, TASK_NOT_FOUND)
    return found[0]


@router.get("/tasks")
async def list_tasks(
    user: CurrentUser,
    db: Database,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    company_id: int | None = None,
    personal: bool = False,
    mine: bool = False,
    kind: Annotated[list[TaskKind] | None, Query()] = None,
    task_status: Annotated[list[TaskStatus] | None, Query(alias="status")] = None,
    missing_amount: bool = False,
    newest_first: bool = False,
    hide_history: bool = False,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TaskList:
    items, total = await task_actions.search(
        db,
        user,
        _show_notices(),
        date_from=date_from,
        date_to=date_to,
        company_id=company_id,
        personal=personal,
        mine=mine,
        kinds=kind,
        statuses=task_status,
        missing_amount=missing_amount,
        newest_first=newest_first,
        hide_history=hide_history,
        limit=limit,
        offset=offset,
    )
    return TaskList(items=items, total=total, today=tasks.today())


@router.get("/tasks/{task_id}")
async def read_task(task_id: int, user: CurrentUser, db: Database) -> TaskDetail | ClientTaskOut:
    found = await task_actions.read(db, user, _show_notices(), task_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, TASK_NOT_FOUND)
    return found


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
async def create_task(body: TaskCreate, user: Staff, db: Database) -> TaskDetail:
    if body.company_id is not None:
        company = await get_accessible_company(db, user, body.company_id)
        if company is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
        if company.is_archived:
            raise HTTPException(status.HTTP_409_CONFLICT, "Компания в архиве")
    try:
        task = await task_actions.create(db, user, body)
    except task_actions.TaskError as error:
        raise _rejected(error) from None
    return await task_actions.read(db, user, True, task.id)


@router.patch("/tasks/{task_id}")
async def update_task(task_id: int, body: TaskPatch, user: Staff, db: Database) -> TaskDetail:
    task = await _editable(db, user, task_id)
    try:
        await task_actions.patch(db, user, task, body)
    except task_actions.TaskError as error:
        raise _rejected(error) from None
    return await task_actions.read(db, user, True, task_id)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: int, user: Staff, db: Database) -> Response:
    task = await _editable(db, user, task_id)
    try:
        await task_actions.delete(db, user, task)
    except task_actions.TaskError as error:
        raise _rejected(error) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/tasks/bulk")
async def bulk(body: BulkIn, user: Staff, db: Database) -> BulkOut:
    ids = set(body.ids)
    found = await task_actions.editable(db, user, ids)
    # Всё или ничего: чужая задача в списке отменяет действие целиком.
    if len(found) != len(ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, TASK_NOT_FOUND)
    updated, skipped = await task_actions.bulk_status(db, user, found, body.status)
    return BulkOut(updated=updated, skipped=skipped)


async def _payment(action, task_id: int, user: User, db: Database):
    try:
        await action(db, user, task_id)
    except payments.PaymentError as error:
        raise HTTPException(error.code, str(error)) from None
    return await task_actions.read(db, user, _show_notices(), task_id)


@router.post("/tasks/{task_id}/mark-paid")
async def mark_paid(task_id: int, user: CurrentUser, db: Database) -> TaskDetail | ClientTaskOut:
    """Только клиент с правом «Клиент платит сам»: planned → paid."""
    return await _payment(payments.mark_paid, task_id, user, db)


@router.post("/tasks/{task_id}/unmark-paid")
async def unmark_paid(task_id: int, user: CurrentUser, db: Database) -> TaskDetail | ClientTaskOut:
    return await _payment(payments.unmark_paid, task_id, user, db)


@router.put("/tasks/nds/{company_id}/{period_key}")
async def set_nds_amount(
    company_id: int,
    period_key: Annotated[str, Path(pattern=r"^\d{4}-Q[1-4]$")],
    body: NdsAmountIn,
    user: Staff,
    db: Database,
) -> list[NdsPart]:
    company = await get_accessible_company(db, user, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    try:
        parts = await tasks.set_nds_amount(db, user, company, period_key, body.amount_kopecks)
    except tasks.NdsPeriodNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Платежей НДС за этот квартал нет") from None
    return [NdsPart.model_validate(task) for task in parts]
