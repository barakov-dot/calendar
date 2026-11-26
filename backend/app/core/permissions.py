"""Права доступа к компаниям. Каждый эндпоинт проверяет их через этот модуль."""

from sqlalchemy import ColumnElement, Select, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, CompanyMember, Role, Task, TaskKind, User


def accessible_company_ids_query(user: User) -> Select[tuple[int]]:
    """Подзапрос с id доступных пользователю компаний.

    admin — все; accountant — где он ответственный; client — к которым привязан
    (архивные клиенту не видны).
    """
    if user.role == Role.ADMIN:
        return select(Company.id)
    if user.role == Role.ACCOUNTANT:
        return select(Company.id).where(Company.accountant_id == user.id)
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
