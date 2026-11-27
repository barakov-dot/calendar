"""Замещение: кому сейчас идут уведомления по компаниям бухгалтера.

Права доступа замещающего проверяются в core.permissions.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Role, Substitution, User

STAFF = (Role.ADMIN, Role.ACCOUNTANT)


def active_on(day: date):
    return (Substitution.date_from <= day, Substitution.date_to >= day)


async def active(db: AsyncSession, day: date, *conditions) -> dict[int, list[int]]:
    """id бухгалтера → id тех, кто его замещает сегодня и подходит под условия."""
    rows = await db.execute(
        select(Substitution.accountant_id, Substitution.substitute_id)
        .join(User, User.id == Substitution.substitute_id)
        .where(*active_on(day), User.is_active.is_(True), User.role.in_(STAFF), *conditions)
        .order_by(Substitution.id)
    )
    found: dict[int, list[int]] = {}
    for accountant_id, substitute_id in rows:
        if substitute_id not in found.setdefault(accountant_id, []):
            found[accountant_id].append(substitute_id)
    return found


def recipients(substitutes: dict[int, list[int]], accountant_id: int) -> list[int]:
    """Замещающие, а если их нет — сам бухгалтер."""
    return substitutes.get(accountant_id) or [accountant_id]


def answers_for(substitutes: dict[int, list[int]], user_id: int) -> set[int]:
    """Чьи компании сейчас входят в рассылку пользователя."""
    found = {accountant for accountant, people in substitutes.items() if user_id in people}
    if user_id not in substitutes:
        found.add(user_id)
    return found
