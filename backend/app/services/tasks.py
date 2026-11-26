"""Генерация задач по правилам и разбивка НДС.

Генерация идемпотентна: ключ (company_id, rule_code, period_key, part). Статусы,
введённые суммы и комментарии она не меняет.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_config
from app.core.settings_store import get_settings
from app.models import ChangedBy, Company, Patent, Task, TaskSource, TaskStatus, User
from app.services import audit, reminders
from app.services.calendar.workdays import WorkCalendar, load_calendar
from app.services.rules.engine import (
    Occurrence,
    RuleBook,
    add_calendar_months,
    load_rules,
    occurrences,
    split_in_three,
)
from app.services.task_state import is_untouched

logger = logging.getLogger(__name__)

NDS_RULE = "nds_payment"


@dataclass
class Result:
    created: int = 0
    updated: int = 0
    deleted: int = 0
    not_required: int = 0
    restored: int = 0
    # годы без производственного календаря и без файла правил
    missing_calendar_years: set[int] = field(default_factory=set)
    missing_rule_years: set[int] = field(default_factory=set)

    def add(self, other: "Result") -> None:
        for name in ("created", "updated", "deleted", "not_required", "restored"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.missing_calendar_years |= other.missing_calendar_years
        self.missing_rule_years |= other.missing_rule_years


@lru_cache(maxsize=4)
def _rules_cached(directory: str, signature: tuple) -> RuleBook:
    return load_rules(Path(directory))


def get_rules() -> RuleBook:
    """Правила перечитываются, когда файлы изменились."""
    directory = Path(get_config().rules_path)
    signature = tuple(
        (path.name, path.stat().st_mtime_ns) for path in sorted(directory.glob("*.yaml"))
    )
    return _rules_cached(str(directory), signature)


def today() -> date:
    return datetime.now(ZoneInfo(get_settings().company.timezone)).date()


def horizon(current: date) -> tuple[date, date]:
    """С 1 января текущего года на generation_horizon_months_ahead месяцев вперёд."""
    months = get_settings().tasks.generation_horizon_months_ahead
    return date(current.year, 1, 1), add_calendar_months(current, months)


def _new_task(company_id: int, item: Occurrence) -> Task:
    return Task(
        company_id=company_id,
        source=TaskSource.RULE,
        rule_code=item.rule_code,
        period_key=item.period_key,
        part=item.part,
        kind=item.kind,
        title=item.title,
        description=item.description,
        source_ref=item.source_ref,
        due_date=item.due_date,
        original_due_date=item.original_due_date,
        needs_amount=item.needs_amount,
        client_visible=item.client_visible,
        amount_kopecks=item.amount_kopecks,
        status=TaskStatus.PLANNED,
    )


def _set_status(task: Task, status: TaskStatus) -> None:
    task.status = status
    task.status_changed_by = None
    task.status_changed_by_role = ChangedBy.SYSTEM
    task.status_changed_at = datetime.now(UTC)


async def generate_tasks(
    db: AsyncSession,
    company_id: int,
    date_from: date,
    date_to: date,
    work_calendar: WorkCalendar,
    current: date,
) -> Result:
    """Создаёт и обновляет задачи компании за интервал. Транзакцию фиксирует вызывающий."""
    result = Result()
    # Блокировка строки компании: две генерации одной компании не идут одновременно.
    company = await db.get(Company, company_id, with_for_update=True, populate_existing=True)
    if company is None or company.is_archived:
        return result
    patents = list(await db.scalars(select(Patent).where(Patent.company_id == company_id)))
    book = get_rules()
    wanted = {
        (item.rule_code, item.period_key, item.part): item
        for item in occurrences(book, company, patents, work_calendar, date_from, date_to)
    }
    existing = {
        (task.rule_code, task.period_key, task.part): task
        for task in await db.scalars(
            select(Task).where(Task.company_id == company_id, Task.source == TaskSource.RULE)
        )
    }

    for key, item in wanted.items():
        task = existing.get(key)
        # Дни выплат могли указать только что: прошедшие выплаты задним числом не заводим.
        if task is None and item.payday and item.due_date < current:
            continue
        if task is not None and item.payday and task.status != TaskStatus.PLANNED:
            continue  # состоявшуюся выплату новое расписание не двигает
        if task is None:
            db.add(_new_task(company_id, item))
            result.created += 1
            continue
        changed = False
        for name in ("due_date", "original_due_date", "title", "source_ref"):
            if name == "due_date" and task.due_overridden:
                continue  # срок изменён вручную
            if getattr(task, name) != getattr(item, name):
                setattr(task, name, getattr(item, name))
                changed = True
        # Пустую сумму можно заполнить (стоимость патента), введённую — не трогаем.
        if (
            task.amount_kopecks is None
            and item.amount_kopecks is not None
            and not task.amount_overridden
            and task.status == TaskStatus.PLANNED
        ):
            task.amount_kopecks = item.amount_kopecks
            changed = True
        if (
            task.status == TaskStatus.NOT_REQUIRED
            and task.status_changed_by_role == ChangedBy.SYSTEM
        ):
            _set_status(task, TaskStatus.PLANNED)
            result.restored += 1
        result.updated += changed

    # Правило перестало подходить. Прошлые задачи и выполненные остаются как есть.
    for key, task in existing.items():
        if key in wanted or task.due_date < current or task.status != TaskStatus.PLANNED:
            continue
        if is_untouched(task):
            await db.delete(task)
            result.deleted += 1
        else:
            _set_status(task, TaskStatus.NOT_REQUIRED)
            result.not_required += 1

    await db.flush()
    result.missing_calendar_years = set(work_calendar.missing_years)
    result.missing_rule_years = {
        year for year in range(date_from.year, date_to.year + 1) if year > book.latest_year
    }
    return result


async def regenerate_company(db: AsyncSession, company_id: int) -> Result:
    current = today()
    date_from, date_to = horizon(current)
    work_calendar = await load_calendar(db)
    result = await generate_tasks(db, company_id, date_from, date_to, work_calendar, current)
    result.created += await reminders.expand_where(db, work_calendar, current, company_id)
    await db.commit()
    return result


async def regenerate_all(db: AsyncSession) -> Result:
    """Все действующие компании, каждая в своей транзакции."""
    total = Result()
    ids = list(await db.scalars(select(Company.id).where(Company.is_archived.is_(False))))
    for company_id in ids:
        total.add(await regenerate_company(db, company_id))
    # личные напоминания не относятся ни к одной компании
    total.created += await reminders.expand_where(db, await load_calendar(db), today())
    await db.commit()
    if total.missing_calendar_years:
        logger.warning(
            "Нет производственного календаря на %s: рабочими считаются пн–пт",
            sorted(total.missing_calendar_years),
        )
    return total


class NdsPeriodNotFound(Exception):
    pass


async def set_nds_amount(
    db: AsyncSession, actor: User, company: Company, period_key: str, total: int
) -> list[Task]:
    """Разносит квартальную сумму НДС на три платежа.

    Части с ручной суммой и уже оплаченные не пересчитываются.
    """
    parts = list(
        await db.scalars(
            select(Task)
            .where(
                Task.company_id == company.id,
                Task.rule_code == NDS_RULE,
                Task.period_key == period_key,
            )
            .order_by(Task.part)
            .with_for_update()
        )
    )
    if not parts:
        raise NdsPeriodNotFound
    amounts = split_in_three(total)
    changed = []
    for task in parts:
        if task.amount_overridden or task.status != TaskStatus.PLANNED:
            continue
        task.amount_kopecks = amounts[task.part - 1]
        changed.append(task.part)
    audit.record(
        db,
        actor.id,
        "task.nds_amount",
        "company",
        company.id,
        {"period": period_key, "total_kopecks": total, "parts": changed},
    )
    await db.commit()
    return parts


def override_amount(task: Task, amount: int | None) -> None:
    """Ручная правка суммы: автопересчёт эту задачу больше не трогает."""
    task.amount_kopecks = amount
    task.amount_overridden = True
