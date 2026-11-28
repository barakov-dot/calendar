from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.models import Company, CompanyMember, CompanyStaff, Role, User
from app.services.inn import with_check_digits
from tests.conftest import JWT_SECRET


async def make_user(
    db: AsyncSession, telegram_id: int, role: Role = Role.ACCOUNTANT, **fields
) -> User:
    fields.setdefault("pd_consent_at", datetime.now(UTC))
    user = User(telegram_id=telegram_id, role=role, **fields)
    db.add(user)
    await db.commit()
    return user


def auth(user: User) -> dict[str, str]:
    token = security.create_token(user.id, "access", JWT_SECRET)
    return {"Authorization": f"Bearer {token}"}


async def make_company(db: AsyncSession, accountant: User | None, number: int = 1, **fields):
    values = {
        "inn": with_check_digits(f"{number:09d}"),
        "name": f"ООО «Компания {number}»",
        "entity_type": "ooo",
        "main_regime": "usn6",
        "region_code": "00",
    } | fields
    company = Company(**values)
    db.add(company)
    await db.commit()
    if accountant:
        await assign(db, company, accountant)
    return company


async def assign(db: AsyncSession, company: Company, *users: User) -> None:
    """Закрепляет за компанией бухгалтеров или помощников."""
    db.add_all(CompanyStaff(company_id=company.id, user_id=user.id) for user in users)
    await db.commit()


async def link_client(db: AsyncSession, company: Company, user: User, **fields) -> None:
    db.add(CompanyMember(company_id=company.id, user_id=user.id, **fields))
    await db.commit()
