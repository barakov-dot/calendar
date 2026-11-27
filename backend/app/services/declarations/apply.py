"""Куда попадут суммы из декларации и запись их в платежи."""

from dataclasses import dataclass, replace

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import accessible_company_ids_query
from app.models import Company, Task, TaskStatus, User
from app.models.company import ProfitAdvances
from app.services import audit, tasks
from app.services.calendar.workdays import load_calendar
from app.services.declarations.parser import Declaration, DeclarationError
from app.services.notify.messages import money


@dataclass(frozen=True)
class Part:
    task: Task
    new_kopecks: int
    # почему сумма не изменится; пусто — будет записана
    kept: str
    # платежа ещё нет: появится вместе с переходом на ежемесячные авансы
    created: bool = False


@dataclass(frozen=True)
class Plan:
    declaration: Declaration
    company: Company
    parts: list[Part]
    switches_to_monthly: bool = False


def _kept(task: Task) -> str:
    """Введённые суммы оплаченных и исправленные вручную платежи не меняются."""
    # в оплаченный платёж без суммы её можно дописать: затирать там нечего
    if task.status == TaskStatus.PAID:
        return "" if task.amount_kopecks is None else "уже оплачен"
    if task.status != TaskStatus.PLANNED:
        return "не в плане"
    if task.amount_overridden:
        return "сумма введена вручную"
    return ""


async def _pay_monthly(db: AsyncSession, user: User, company: Company) -> set[int]:
    """Переводит на ежемесячные авансы и создаёт платежи. Возвращает id прежних задач."""
    before = set(await db.scalars(select(Task.id).where(Task.company_id == company.id)))
    company.profit_advances_mode = ProfitAdvances.MONTHLY_BY_QUARTER
    audit.record(
        db,
        user.id,
        "company.update",
        "company",
        company.id,
        {"profit_advances_mode": [ProfitAdvances.QUARTERLY, company.profit_advances_mode]},
    )
    await db.flush()
    current = tasks.today()
    await tasks.generate_tasks(
        db, company.id, *tasks.horizon(current), await load_calendar(db), current
    )
    return before


async def plan(db: AsyncSession, user: User, declaration: Declaration, lock: bool = False) -> Plan:
    """Находит организацию по ИНН и платежи, к которым относятся суммы декларации.

    Ежемесячные авансы в декларации означают, что организация платит помесячно. Если в
    карточке стоят только квартальные, настройка меняется в текущей транзакции: apply её
    сохраняет, а предпросмотр должен откатить.
    """
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
    switch = company.profit_advances_mode == ProfitAdvances.QUARTERLY and any(
        item.rule_code == "profit_monthly" and item.amount_kopecks for item in declaration.items
    )
    before = await _pay_monthly(db, user, company) if switch else None
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

    parts, warnings = [], list(declaration.warnings)
    for item, key in zip(declaration.items, keys, strict=True):
        task = found.get(key)
        if task is not None:
            created = before is not None and task.id not in before
            parts.append(Part(task, item.amount_kopecks, _kept(task), created))
        elif item.amount_kopecks:
            warnings.append(
                f"Нет платежа «{item.label}»: {money(item.amount_kopecks)} записать некуда. "
                "Проверьте настройки организации."
            )
    parts.sort(key=lambda part: part.task.due_date)
    if any(part.kept and (part.task.amount_kopecks or 0) != part.new_kopecks for part in parts):
        warnings.append(
            "Часть платежей не меняется, и их суммы отличаются от декларации. Проверьте разницу."
        )
    return Plan(replace(declaration, warnings=tuple(warnings)), company, parts, switch)


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
