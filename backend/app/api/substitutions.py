"""Замещения. Назначает администратор; участники видят свои."""

from datetime import date

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, model_validator
from sqlalchemy import or_, select

from app.api.deps import CurrentUser, Database, ManagerUser
from app.models import Substitution, User
from app.schemas.company import Input
from app.services import audit, tasks
from app.services.companies import person_name
from app.services.substitutions import STAFF

router = APIRouter()


class SubstitutionIn(Input):
    accountant_id: int
    substitute_id: int
    date_from: date
    date_to: date

    @model_validator(mode="after")
    def consistent(self) -> "SubstitutionIn":
        if self.accountant_id == self.substitute_id:
            raise ValueError("выберите двух разных сотрудников")
        if self.date_to < self.date_from:
            raise ValueError("конец раньше начала")
        return self


class SubstitutionOut(BaseModel):
    id: int
    accountant_id: int
    accountant_name: str
    substitute_id: int
    substitute_name: str
    date_from: date
    date_to: date
    active: bool


async def _list(db: Database, *conditions) -> list[SubstitutionOut]:
    """Действующие и будущие."""
    current = tasks.today()
    rows = await db.scalars(
        select(Substitution)
        .where(Substitution.date_to >= current, *conditions)
        .order_by(Substitution.date_from, Substitution.id)
    )
    return [
        SubstitutionOut(
            id=row.id,
            accountant_id=row.accountant_id,
            accountant_name=person_name(await db.get(User, row.accountant_id)),
            substitute_id=row.substitute_id,
            substitute_name=person_name(await db.get(User, row.substitute_id)),
            date_from=row.date_from,
            date_to=row.date_to,
            active=row.date_from <= current,
        )
        for row in rows
    ]


@router.get("/me/substitutions")
async def my_substitutions(user: CurrentUser, db: Database) -> list[SubstitutionOut]:
    return await _list(
        db,
        or_(Substitution.accountant_id == user.id, Substitution.substitute_id == user.id),
    )


@router.get("/admin/substitutions")
async def list_substitutions(_: ManagerUser, db: Database) -> list[SubstitutionOut]:
    return await _list(db)


@router.post("/admin/substitutions", status_code=status.HTTP_201_CREATED)
async def create(body: SubstitutionIn, admin: ManagerUser, db: Database) -> list[SubstitutionOut]:
    for user_id in (body.accountant_id, body.substitute_id):
        user = await db.get(User, user_id)
        if user is None or not user.is_active or user.role not in STAFF:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Замещать можно только действующих бухгалтеров и администраторов",
            )
    if body.date_to < tasks.today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Этот период уже прошёл")
    overlapping = await db.scalar(
        select(Substitution.id).where(
            Substitution.accountant_id == body.accountant_id,
            Substitution.substitute_id == body.substitute_id,
            Substitution.date_from <= body.date_to,
            Substitution.date_to >= body.date_from,
        )
    )
    if overlapping is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Такое замещение на эти дни уже есть"
        )
    row = Substitution(**body.model_dump(), created_by=admin.id)
    db.add(row)
    await db.flush()
    audit.record(
        db, admin.id, "substitution.create", "substitution", row.id, body.model_dump(mode="json")
    )
    await db.commit()
    return await _list(db)


@router.delete("/admin/substitutions/{substitution_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(substitution_id: int, admin: ManagerUser, db: Database) -> Response:
    row = await db.get(Substitution, substitution_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Замещение не найдено")
    audit.record(db, admin.id, "substitution.delete", "substitution", row.id)
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
