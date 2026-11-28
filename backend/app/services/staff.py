"""Кто из сотрудников закреплён за компаниями: бухгалтеры и помощники."""

from dataclasses import dataclass, field

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EDITORS, CompanyStaff, Role, User


@dataclass
class Team:
    accountants: list[User] = field(default_factory=list)
    assistants: list[User] = field(default_factory=list)


def companies_of(*conditions) -> Select[tuple[int]]:
    """Подзапрос с id компаний сотрудников, подходящих под условия на CompanyStaff."""
    return select(CompanyStaff.company_id).where(*conditions)


async def teams(db: AsyncSession, *conditions) -> dict[int, Team]:
    """id компании → её сотрудники. Без условий — по всем компаниям."""
    rows = await db.execute(
        select(CompanyStaff.company_id, User)
        .join(User, User.id == CompanyStaff.user_id)
        .where(*conditions)
        .order_by(CompanyStaff.company_id, User.id)
    )
    found: dict[int, Team] = {}
    for company_id, user in rows:
        team = found.setdefault(company_id, Team())
        if user.role in EDITORS:
            team.accountants.append(user)
        elif user.role == Role.ASSISTANT:
            team.assistants.append(user)
    return found


async def team(db: AsyncSession, company_id: int) -> Team:
    found = await teams(db, CompanyStaff.company_id == company_id)
    return found.get(company_id, Team())
