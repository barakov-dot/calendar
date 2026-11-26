"""Задачи. Пока только ввод квартальной суммы НДС; списки и статусы — в Фазе 5."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.companies import NOT_FOUND, Staff
from app.api.deps import Database
from app.core.permissions import get_accessible_company
from app.schemas.company import MAX_KOPECKS
from app.services import tasks

router = APIRouter()


class NdsAmountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_kopecks: int = Field(ge=0, le=MAX_KOPECKS)


class NdsPartOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    part: int
    due_date: date
    amount_kopecks: int | None
    amount_overridden: bool
    status: str


@router.put("/tasks/nds/{company_id}/{period_key}")
async def set_nds_amount(
    company_id: int,
    period_key: Annotated[str, Path(pattern=r"^\d{4}-Q[1-4]$")],
    body: NdsAmountIn,
    user: Staff,
    db: Database,
) -> list[NdsPartOut]:
    company = await get_accessible_company(db, user, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    try:
        parts = await tasks.set_nds_amount(db, user, company, period_key, body.amount_kopecks)
    except tasks.NdsPeriodNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Платежей НДС за этот квартал нет") from None
    return [NdsPartOut.model_validate(task) for task in parts]
