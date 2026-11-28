"""Пользователи глазами администратора: список, карточка, изменение имени и доступа."""

import re

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import business_today
from app.models import (
    MANAGERS,
    Company,
    CompanyMember,
    CompanyStaff,
    Role,
    Substitution,
    User,
)
from app.services import audit, staff
from app.services.companies import person_name
from app.services.login_code import normalize

LOGIN_PATTERN = re.compile(r"[a-z0-9_.-]{3,32}")


class PersonError(Exception):
    """Изменение неприменимо. Текст показывается пользователю."""


async def search(db: AsyncSession, role: str | None = None, q: str = "") -> list[tuple[User, int]]:
    """Все пользователи и число действующих компаний каждого."""
    own = (
        select(CompanyStaff.user_id, func.count().label("total"))
        .join(Company, Company.id == CompanyStaff.company_id)
        .where(Company.is_archived.is_(False))
        .group_by(CompanyStaff.user_id)
        .subquery()
    )
    linked = (
        select(CompanyMember.user_id, func.count().label("total"))
        .join(Company, Company.id == CompanyMember.company_id)
        .where(Company.is_archived.is_(False))
        .group_by(CompanyMember.user_id)
        .subquery()
    )
    query = (
        select(User, func.coalesce(own.c.total, 0) + func.coalesce(linked.c.total, 0))
        .outerjoin(own, own.c.user_id == User.id)
        .outerjoin(linked, linked.c.user_id == User.id)
        .order_by(func.lower(User.first_name), func.lower(User.last_name), User.id)
    )
    if role:
        query = query.where(User.role == role)
    if text := q.strip().lstrip("@"):
        full = func.concat(User.first_name, " ", User.last_name)
        query = query.where(
            or_(
                full.icontains(text, autoescape=True),
                User.username.icontains(text, autoescape=True),
            )
        )
    return [(user, total) for user, total in await db.execute(query)]


async def accountant_companies(db: AsyncSession, user: User) -> list[Company]:
    return list(
        await db.scalars(
            select(Company)
            .where(Company.id.in_(staff.companies_of(CompanyStaff.user_id == user.id)))
            .order_by(Company.is_archived, func.lower(Company.name))
        )
    )


async def client_companies(db: AsyncSession, user: User) -> list[tuple[Company, CompanyMember]]:
    rows = await db.execute(
        select(Company, CompanyMember)
        .join(CompanyMember, CompanyMember.company_id == Company.id)
        .where(CompanyMember.user_id == user.id)
        .order_by(Company.is_archived, func.lower(Company.name))
    )
    return [(company, member) for company, member in rows]


async def substitutions_of(db: AsyncSession, user: User) -> list[tuple[Substitution, str, str]]:
    """Идущие и будущие замещения, где участвует пользователь."""
    rows = await db.scalars(
        select(Substitution)
        .where(
            or_(Substitution.accountant_id == user.id, Substitution.substitute_id == user.id),
            Substitution.date_to >= business_today(),
        )
        .order_by(Substitution.date_from, Substitution.id)
    )
    found = []
    for item in rows:
        accountant = await db.get(User, item.accountant_id)
        substitute = await db.get(User, item.substitute_id)
        found.append((item, person_name(accountant), person_name(substitute)))
    return found


async def _set_login(db: AsyncSession, user: User, value: str) -> bool:
    """Пустая строка убирает логин. True — изменился."""
    key = normalize(value) or None
    if key == user.login:
        return False
    if key is not None:
        if not LOGIN_PATTERN.fullmatch(key):
            raise PersonError(
                "Логин: от 3 до 32 знаков, латинские буквы, цифры, точка, дефис или _"
            )
        # чужой @username тоже занят: иначе по нему вошли бы не в тот аккаунт
        taken = await db.scalar(
            select(User.id)
            .where(User.id != user.id, or_(User.login == key, func.lower(User.username) == key))
            .limit(1)
        )
        if taken is not None:
            raise PersonError("Такой логин уже занят")
    user.login = key
    return True


async def update(
    db: AsyncSession,
    actor: User,
    user: User,
    *,
    first_name: str | None = None,
    last_name: str | None = None,
    is_active: bool | None = None,
    role: str | None = None,
    login: str | None = None,
    reset_name: bool = False,
) -> None:
    # главный бухгалтер не управляет администратором и другими главными бухгалтерами
    if actor.role != Role.ADMIN and user.id != actor.id and user.role in MANAGERS:
        raise PersonError("Администратора и главных бухгалтеров меняет только администратор")
    if user.id == actor.id and is_active is False:
        raise PersonError("Отключить собственный доступ нельзя")
    changed: dict = {}
    if role is not None and role != user.role:
        if actor.role != Role.ADMIN:
            raise PersonError("Роль меняет только администратор")
        if user.role not in (Role.ACCOUNTANT, Role.CHIEF):
            raise PersonError("Роль меняется только между бухгалтером и главным бухгалтером")
        user.role = role
        changed["role"] = role
    renamed = False
    for field, value in (("first_name", first_name), ("last_name", last_name)):
        if value is not None and getattr(user, field) != value:
            setattr(user, field, value)
            renamed = True
    if renamed:
        if not f"{user.first_name}{user.last_name}":
            raise PersonError("Укажите имя или фамилию")
        # имя, заданное администратором, Telegram больше не перезаписывает
        user.name_overridden = True
        changed["name"] = None  # персональные данные в журнал не пишутся
    elif reset_name and user.name_overridden:
        user.name_overridden = False
        changed["name_from_telegram"] = True
    if is_active is not None and user.is_active != is_active:
        if user.role == Role.ADMIN:
            raise PersonError("Доступ администратора здесь не отключается")
        user.is_active = is_active
        changed["is_active"] = is_active
    if login is not None and await _set_login(db, user, login):
        changed["login"] = None  # может содержать фамилию
    if changed:
        audit.record(db, actor.id, "user.update", "user", user.id, changed)
        await db.commit()
