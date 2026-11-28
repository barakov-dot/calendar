"""Куда попадут суммы из декларации и запись их в платежи."""

from dataclasses import dataclass, field, replace

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import accessible_company_ids_query
from app.models import Company, Task, TaskStatus, User
from app.models.company import ProfitAdvances
from app.services import audit, tasks
from app.services.calendar.workdays import load_calendar
from app.services.declarations.parser import Declaration, DeclarationError
from app.services.notify.messages import money

# названия признаков карточки, как они подписаны на экране
FLAG_NAMES = {
    "has_property_avg": "Имущество по среднегодовой стоимости",
    "has_transport_tax": "Транспортный налог",
    "has_land_tax": "Земельный налог",
    "has_property_advances": "Платит авансы по имущественным налогам",
}


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
    # что будет отмечено в карточке компании при записи
    enables: list[str] = field(default_factory=list)


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


def _needed_changes(company: Company, declaration: Declaration) -> dict:
    """Что отметить в карточке, чтобы появились платежи для сумм из файла.

    Сумма в декларации или уведомлении означает, что налог организация платит.
    """
    amounts = {item.rule_code for item in declaration.items if item.amount_kopecks}
    changes: dict = {}
    if "profit_monthly" in amounts and company.profit_advances_mode == ProfitAdvances.QUARTERLY:
        changes["profit_advances_mode"] = ProfitAdvances.MONTHLY_BY_QUARTER
    if company.entity_type != "ooo":
        return changes
    taxed = {code.split("_")[0] for code in amounts}
    if "property" in taxed and not (company.has_property_avg or company.has_property_cadastral):
        changes["has_property_avg"] = True
    for tax, flag in (("transport", "has_transport_tax"), ("land", "has_land_tax")):
        if tax in taxed and not getattr(company, flag):
            changes[flag] = True
    advances = {"property_advance", "transport_advance", "land_advance"}
    if amounts & advances and not company.has_property_advances:
        changes["has_property_advances"] = True
    return changes


async def _change_company(
    db: AsyncSession, user: User, company: Company, changes: dict
) -> set[int]:
    """Меняет карточку и создаёт появившиеся платежи. Возвращает id прежних задач."""
    before = set(await db.scalars(select(Task.id).where(Task.company_id == company.id)))
    for name, value in changes.items():
        setattr(company, name, value)
    audit.record(db, user.id, "company.update", "company", company.id, {"changes": changes})
    await db.flush()
    current = tasks.today()
    await tasks.generate_tasks(
        db, company.id, *tasks.horizon(current), await load_calendar(db), current
    )
    return before


def _property_kind(company: Company, declaration: Declaration) -> tuple[Declaration, list[str]]:
    """В уведомлении имущество не разделено по виду стоимости: решает карточка компании."""
    generic = ("property_advance", "property_year")
    if not any(item.rule_code in generic for item in declaration.items):
        return declaration, []
    average = company.has_property_avg or not company.has_property_cadastral
    prefix = "property_avg" if average else "property_cad"
    items = tuple(
        replace(item, rule_code=item.rule_code.replace("property", prefix, 1))
        if item.rule_code in generic
        else item
        for item in declaration.items
    )
    warnings = []
    if company.has_property_avg and company.has_property_cadastral:
        warnings.append(
            "Сумма налога на имущество записана в платёж по среднегодовой стоимости: в "
            "уведомлении она одна. Платёж по кадастровой стоимости отметьте «Не требуется» или "
            "разделите сумму вручную."
        )
    return replace(declaration, items=items), warnings


async def plan(db: AsyncSession, user: User, declaration: Declaration, lock: bool = False) -> Plan:
    """Находит организацию по ИНН и платежи, к которым относятся суммы декларации.

    Если для сумм нет платежей из-за настроек (помесячные авансы по прибыли, транспортный
    налог и т. п.), карточка меняется в текущей транзакции: apply это сохраняет, а
    предпросмотр должен откатить.
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
    changes = _needed_changes(company, declaration)
    before = await _change_company(db, user, company, changes) if changes else None
    declaration, property_warnings = _property_kind(company, declaration)
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
            "организации тип (ООО или ИП), режим налогообложения, «Плательщик НДС» и порядок "
            "авансов по прибыли."
        )

    parts, warnings = [], [*declaration.warnings, *property_warnings]
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
    return Plan(
        replace(declaration, warnings=tuple(warnings)),
        company,
        parts,
        switches_to_monthly="profit_advances_mode" in changes,
        enables=[FLAG_NAMES[name] for name in changes if name in FLAG_NAMES],
    )


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
