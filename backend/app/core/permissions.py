"""Права доступа к компаниям. Каждый эндпоинт проверяет их через этот модуль."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings_store import get_settings
from app.models import (
    MANAGERS,
    Company,
    CompanyMember,
    CompanyStaff,
    Role,
    Substitution,
    Task,
    TaskKind,
    User,
)


def business_today() -> date:
    return datetime.now(ZoneInfo(get_settings().company.timezone)).date()


def _accountant_condition(user: User, on: date | None) -> ColumnElement[bool]:
    """Свои компании и компании тех, кого бухгалтер замещает в этот день."""
    day = on or business_today()
    replaced = select(Substitution.accountant_id).where(
        Substitution.substitute_id == user.id,
        Substitution.date_from <= day,
        Substitution.date_to >= day,
    )
    return Company.id.in_(
        select(CompanyStaff.company_id).where(
            or_(CompanyStaff.user_id == user.id, CompanyStaff.user_id.in_(replaced))
        )
    )


def accessible_company_ids_query(user: User, on: date | None = None) -> Select[tuple[int]]:
    """Подзапрос с id доступных пользователю компаний.

    admin и chief — все; accountant — где он закреплён или замещает закреплённого;
    assistant — где закреплён (только чтение); client — к которым привязан (архивные
    клиенту не видны).
    """
    if user.role in MANAGERS:
        return select(Company.id)
    if user.role == Role.ACCOUNTANT:
        return select(Company.id).where(_accountant_condition(user, on))
    if user.role == Role.ASSISTANT:
        return select(CompanyStaff.company_id).where(CompanyStaff.user_id == user.id)
    if user.role == Role.CLIENT:
        return (
            select(Company.id)
            .join(CompanyMember, CompanyMember.company_id == Company.id)
            .where(CompanyMember.user_id == user.id, Company.is_archived.is_(False))
        )
    raise ValueError(f"неизвестная роль: {user.role}")


async def get_accessible_company_ids(db: AsyncSession, user: User) -> set[int]:
    return set(await db.scalars(accessible_company_ids_query(user)))


async def get_accessible_company(db: AsyncSession, user: User, company_id: int) -> Company | None:
    """Компания, если она доступна пользователю."""
    return await db.scalar(
        select(Company).where(
            Company.id == company_id, Company.id.in_(accessible_company_ids_query(user))
        )
    )


def client_task_condition(show_notices: bool) -> ColumnElement[bool]:
    """Какие задачи доступных компаний видит клиент. Все клиентские выборки задач
    обязаны применять это условие вместе с проверкой компании.

    show_notices — настройка tasks.show_notices_to_clients (уведомления в ФНС).
    """
    visible = Task.client_visible.is_(True)
    return visible if show_notices else and_(visible, Task.kind != TaskKind.NOTICE)


def visible_task_condition(
    user: User, show_notices: bool, on: date | None = None
) -> ColumnElement[bool]:
    """Какие задачи пользователь вправе читать, включая личные напоминания."""
    company_task = Task.company_id.in_(accessible_company_ids_query(user, on))
    if user.role == Role.CLIENT:
        return and_(company_task, client_task_condition(show_notices))
    if user.role == Role.ADMIN:
        return or_(company_task, Task.company_id.is_(None))
    return or_(company_task, Task.owner_id == user.id)


def editable_task_condition(user: User, on: date | None = None) -> ColumnElement[bool]:
    """Какие задачи пользователь вправе менять. Помощник и клиент — никакие."""
    if user.role == Role.ADMIN:
        return or_(
            Task.company_id.in_(accessible_company_ids_query(user)), Task.company_id.is_(None)
        )
    # личные задачи других людей главный бухгалтер не видит и не меняет
    if user.role in (Role.CHIEF, Role.ACCOUNTANT):
        return or_(
            Task.company_id.in_(accessible_company_ids_query(user, on)), Task.owner_id == user.id
        )
    raise ValueError(f"роль без права изменения задач: {user.role}")
