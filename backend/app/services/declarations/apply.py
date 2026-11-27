"""Куда попадёт сумма из декларации и запись её в платежи."""

from dataclasses import dataclass, replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import accessible_company_ids_query
from app.models import Company, Task, TaskStatus, User
from app.services import tasks
from app.services.declarations.parser import DeclarationError, NdsDeclaration
from app.services.notify.messages import money
from app.services.rules.engine import split_in_three


@dataclass(frozen=True)
class Part:
    task: Task
    new_kopecks: int
    # почему сумма не изменится; пусто — будет записана
    kept: str


@dataclass(frozen=True)
class Plan:
    declaration: NdsDeclaration
    company: Company
    parts: list[Part]


def _kept(task: Task) -> str:
    # те же условия, что в tasks.set_nds_amount
    if task.status == TaskStatus.PAID:
        return "уже оплачен"
    if task.status != TaskStatus.PLANNED:
        return "не в плане"
    if task.amount_overridden:
        return "сумма введена вручную"
    return ""


async def plan(db: AsyncSession, user: User, declaration: NdsDeclaration) -> Plan:
    """Находит организацию по ИНН и три платежа за квартал декларации."""
    company = await db.scalar(
        select(Company).where(
            Company.inn == declaration.inn,
            Company.id.in_(accessible_company_ids_query(user)),
        )
    )
    # чужая и отсутствующая организации отвечают одинаково
    if company is None:
        raise DeclarationError(f"Организации с ИНН {declaration.inn} нет среди ваших")
    if company.is_archived:
        raise DeclarationError("Организация в архиве")
    found = list(
        await db.scalars(
            select(Task)
            .where(
                Task.company_id == company.id,
                Task.rule_code == tasks.NDS_RULE,
                Task.period_key == declaration.period_key,
            )
            .order_by(Task.part)
        )
    )
    if not found:
        raise DeclarationError(
            f"Платежей НДС за {declaration.quarter} квартал {declaration.year} года нет. "
            "Проверьте, что в карточке организации отмечено «Плательщик НДС»."
        )
    amounts = split_in_three(declaration.total_kopecks)
    parts = [Part(task, amounts[task.part - 1], _kept(task)) for task in found]
    # оплаченные и ручные части остаются, и сумма платежей может разойтись с декларацией
    after = sum(
        (part.task.amount_kopecks or 0) if part.kept else part.new_kopecks for part in parts
    )
    if after != declaration.total_kopecks:
        warning = (
            f"Три платежа в сумме дадут {money(after)}, а по декларации "
            f"{money(declaration.total_kopecks)}. Проверьте платежи, которые не меняются."
        )
        declaration = replace(declaration, warnings=(*declaration.warnings, warning))
    return Plan(declaration, company, parts)


async def apply(db: AsyncSession, user: User, found: Plan) -> None:
    await tasks.set_nds_amount(
        db,
        user,
        found.company,
        found.declaration.period_key,
        found.declaration.total_kopecks,
        correction=found.declaration.correction,
    )
