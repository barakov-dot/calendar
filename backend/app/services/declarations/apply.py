"""Куда попадут суммы из декларации и запись их в платежи."""

from dataclasses import dataclass, replace

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import accessible_company_ids_query
from app.models import Company, Task, TaskStatus, User
from app.models.company import ProfitAdvances
from app.services import audit
from app.services.declarations.parser import Declaration, DeclarationError, Item
from app.services.notify.messages import money


@dataclass(frozen=True)
class Part:
    task: Task
    new_kopecks: int
    # почему сумма не изменится; пусто — будет записана
    kept: str


@dataclass(frozen=True)
class Plan:
    declaration: Declaration
    company: Company
    parts: list[Part]


def _kept(task: Task) -> str:
    """Оплаченные и исправленные вручную платежи не меняются."""
    if task.status == TaskStatus.PAID:
        return "уже оплачен"
    if task.status != TaskStatus.PLANNED:
        return "не в плане"
    if task.amount_overridden:
        return "сумма введена вручную"
    return ""


def _missing(company: Company, items: list[Item]) -> list[str]:
    """Суммы, для которых нет платежа: чаще всего из-за настроек организации."""
    warnings = []
    monthly = [item for item in items if item.rule_code == "profit_monthly"]
    if monthly and company.profit_advances_mode == ProfitAdvances.QUARTERLY:
        listed = "; ".join(f"{item.label} — {money(item.amount_kopecks)}" for item in monthly)
        warnings.append(
            "В декларации есть ежемесячные авансы, а в карточке организации выбраны только "
            "квартальные. Если организация платит ежемесячно, измените «Авансы по налогу на "
            f"прибыль» и загрузите декларацию ещё раз. Не записано: {listed}."
        )
        items = [item for item in items if item not in monthly]
    return warnings + [
        f"Нет платежа «{item.label}»: {money(item.amount_kopecks)} записать некуда. "
        "Проверьте настройки организации."
        for item in items
    ]


async def plan(db: AsyncSession, user: User, declaration: Declaration, lock: bool = False) -> Plan:
    """Находит организацию по ИНН и платежи, к которым относятся суммы декларации."""
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
    keys = [(item.rule_code, item.period_key, item.part) for item in declaration.items]
    query = select(Task).where(
        Task.company_id == company.id,
        tuple_(Task.rule_code, Task.period_key, Task.part).in_(keys),
    )
    found = {
        (task.rule_code, task.period_key, task.part): task
        for task in await db.scalars(query.with_for_update() if lock else query)
    }
    if not found:
        raise DeclarationError(
            f"{declaration.title}: платежей для этих сумм нет. Проверьте в карточке "
            "организации режим налогообложения, «Плательщик НДС» и порядок авансов по прибыли."
        )

    parts, missing = [], []
    for item, key in zip(declaration.items, keys, strict=True):
        task = found.get(key)
        if task is None:
            missing.append(item)
        else:
            parts.append(Part(task, item.amount_kopecks, _kept(task)))
    warnings = [*declaration.warnings, *_missing(company, missing)]
    parts.sort(key=lambda part: part.task.due_date)
    if any(part.kept and part.task.amount_kopecks != part.new_kopecks for part in parts):
        warnings.append(
            "Часть платежей не меняется, и их суммы отличаются от декларации. Проверьте разницу."
        )
    return Plan(replace(declaration, warnings=tuple(warnings)), company, parts)


async def apply(db: AsyncSession, user: User, found: Plan) -> None:
    """Записывает суммы по плану, составленному с блокировкой задач."""
    changed = []
    for part in found.parts:
        if part.kept:
            continue
        part.task.amount_kopecks = part.new_kopecks
        changed.append({"task_id": part.task.id, "kopecks": part.new_kopecks})
    audit.record(
        db,
        user.id,
        "task.declaration_amounts",
        "company",
        found.company.id,
        {
            "declaration": found.declaration.title,
            "correction": found.declaration.correction,
            "tasks": changed,
        },
    )
    await db.commit()
