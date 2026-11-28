"""Тестовые пользователи и компании: python -m app.seed_dev (make seed-dev).

ИНН выдуманные (код региона 00), с настоящими организациями не пересекаются.
"""

import asyncio
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_config
from app.core.db import get_engine, get_sessionmaker
from app.models import Company, CompanyMember, CompanyStaff, Patent, Role, User
from app.schemas.company import CompanyData
from app.services.calendar.workdays import load_missing_years
from app.services.inn import with_check_digits
from app.services.tasks import regenerate_all

# Отрицательные telegram_id не пересекаются с настоящими пользователями.
DEV_USERS = (
    (-1, Role.ADMIN, "Анна", "Админова"),
    (-2, Role.ACCOUNTANT, "Борис", "Бухгалтеров"),
    (-3, Role.ACCOUNTANT, "Вера", "Балансова"),
    (-4, Role.CLIENT, "Клиент", "Первый"),
    (-5, Role.CLIENT, "Клиент", "Второй"),
    (-6, Role.CLIENT, "Клиент", "Платит сам"),
    (-7, Role.ASSISTANT, "Дина", "Помощникова"),
)


# (основа ИНН, telegram_id бухгалтера, клиенты [(telegram_id, платит сам)], поля)
DEV_COMPANIES = (
    (
        "000000001",
        -2,
        [(-4, False)],
        {
            "name": "ООО «Тест Общая»",
            "entity_type": "ooo",
            "main_regime": "osno",
            "profit_advances_mode": "monthly_by_quarter",
            "has_employees": True,
            "has_property_avg": True,
            "has_property_cadastral": True,
            "advance_day": 25,
            "salary_day": 10,
            "has_land_tax": True,
        },
    ),
    (
        "000000002",
        -2,
        [(-5, False), (-6, True)],
        {
            "name": "ООО «Тест Доходы»",
            "entity_type": "ooo",
            "main_regime": "usn6",
            "has_employees": True,
            "has_transport_tax": True,
            "has_trade_fee": True,
        },
    ),
    (
        "0000000003",
        -2,
        [(-6, True)],
        {
            "name": "ИП Тестов (УСН и патент)",
            "entity_type": "ip",
            "main_regime": "usn15",
            "has_tourist_tax": True,
        },
    ),
    (
        "0000000004",
        -3,
        [],
        {
            "name": "ИП Тестова АУСН",
            "entity_type": "ip",
            "main_regime": "ausn_income",
            "has_employees": True,
        },
    ),
    (
        "0000000005",
        -3,
        [(-4, False)],
        {
            "name": "ИП Тестин ОСНО",
            "has_transport_tax": True,
            "has_land_tax": True,
            "entity_type": "ip",
            "main_regime": "osno",
            "has_employees": True,
        },
    ),
)
PATENT_OWNER = "0000000003"


def dev_company_data(base: str, fields: dict) -> CompanyData:
    return CompanyData(inn=with_check_digits(base), short_name=fields["name"], **fields)


def dev_patent(year: int) -> dict:
    return {
        "number": "TEST-1",
        "date_start": date(year, 1, 1),
        "date_end": date(year, 12, 31),
        "cost_kopecks": 3_600_000,
    }


async def seed_companies(db: AsyncSession) -> None:
    users = {user.telegram_id: user.id for user in await db.scalars(select(User))}
    for base, accountant, members, fields in DEV_COMPANIES:
        inn = with_check_digits(base)
        if await db.scalar(select(Company.id).where(Company.inn == inn)):
            continue
        data = dev_company_data(base, fields)
        company = Company(**data.model_dump())
        db.add(company)
        await db.flush()
        db.add(CompanyStaff(company_id=company.id, user_id=users[accountant]))
        db.add(CompanyStaff(company_id=company.id, user_id=users[-7]))
        if base == PATENT_OWNER:
            db.add(Patent(company_id=company.id, **dev_patent(date.today().year)))
        db.add_all(
            CompanyMember(
                company_id=company.id,
                user_id=users[telegram_id],
                is_primary=index == 0,
                can_mark_paid=pays_self,
            )
            for index, (telegram_id, pays_self) in enumerate(members)
        )


async def seed(db: AsyncSession) -> None:
    for telegram_id, role, first_name, last_name in DEV_USERS:
        await db.execute(
            insert(User)
            .values(
                telegram_id=telegram_id,
                role=role,
                first_name=first_name,
                last_name=last_name,
                pd_consent_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(index_elements=[User.telegram_id])
        )
    await seed_companies(db)
    await db.commit()
    await load_missing_years(db, Path(get_config().data_path) / "calendar")
    await regenerate_all(db)


async def main() -> None:
    async with get_sessionmaker()() as db:
        await seed(db)
    await get_engine().dispose()


if __name__ == "__main__":
    if not get_config().is_dev:
        sys.exit("seed-dev доступен только при APP_ENV=dev")
    asyncio.run(main())
    print(f"Готово: пользователей {len(DEV_USERS)}, компаний {len(DEV_COMPANIES)}")
