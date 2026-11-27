"""Действия сотрудников с задачами. Права проверяются условиями из core.permissions."""

from datetime import UTC, date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import editable_task_condition, visible_task_condition
from app.models import (
    Attachment,
    Company,
    RecurringReminder,
    Role,
    Task,
    TaskKind,
    TaskSource,
    TaskStatus,
    User,
)
from app.schemas.task import (
    ClientTaskOut,
    NdsPart,
    TaskCreate,
    TaskDetail,
    TaskOut,
    TaskPatch,
)
from app.services import audit, payments
from app.services.calendar.workdays import load_calendar
from app.services.companies import person_name
from app.services.reminders import shift
from app.services.tasks import NDS_RULE, override_amount

AMOUNT_KINDS = (TaskKind.PAYMENT, TaskKind.OTHER)
# Тексты и пояснения в журнал не пишутся: там могут быть персональные данные.
NOT_JOURNALED = {"description", "comment", "client_note"}


class TaskError(Exception):
    """Действие неприменимо. Текст показывается пользователю."""


def status_allowed(kind: str, status: str) -> bool:
    """Платежи отмечаются «оплачено», остальное — «сдано»."""
    if status == TaskStatus.PAID:
        return kind == TaskKind.PAYMENT
    if status == TaskStatus.DONE:
        return kind != TaskKind.PAYMENT
    return True


def _set_status(task: Task, status: str, actor: User) -> None:
    task.status = status
    task.status_changed_by = actor.id
    task.status_changed_by_role = actor.role
    task.status_changed_at = datetime.now(UTC)


def _query(user: User, show_notices: bool):
    return (
        select(Task, Company, User)
        .outerjoin(Company, Company.id == Task.company_id)
        .outerjoin(User, User.id == Task.status_changed_by)
        .where(visible_task_condition(user, show_notices))
    )


def _view(
    user: User,
    task: Task,
    company: Company | None,
    changed_by: User | None,
    payer_ids: set[int] = frozenset(),
):
    values = {name: getattr(task, name) for name in TaskOut.model_fields if hasattr(task, name)}
    values["company_name"] = (company.short_name or company.name) if company else "Личная задача"
    if user.role == Role.CLIENT:
        may = task.company_id in payer_ids and task.kind == TaskKind.PAYMENT
        values["can_mark_paid"] = may and task.status == TaskStatus.PLANNED
        values["can_unmark_paid"] = may and payments.can_unmark(task, user, datetime.now(UTC))
        return ClientTaskOut.model_validate(values)
    return TaskOut.model_validate(values | {"status_changed_by_name": person_name(changed_by)})


async def _payer_ids(db: AsyncSession, user: User) -> set[int]:
    return await payments.payer_company_ids(db, user) if user.role == Role.CLIENT else set()


async def search(
    db: AsyncSession,
    user: User,
    show_notices: bool,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    company_id: int | None = None,
    personal: bool = False,
    mine: bool = False,
    kinds: list[str] | None = None,
    statuses: list[str] | None = None,
    missing_amount: bool = False,
    newest_first: bool = False,
    limit: int = 500,
    offset: int = 0,
) -> tuple[list, int]:
    query = _query(user, show_notices)
    if company_id is not None:
        query = query.where(Task.company_id == company_id)
    else:
        # в общих списках архивные компании не показываются
        query = query.where(or_(Task.company_id.is_(None), Company.is_archived.is_(False)))
    if personal:
        query = query.where(Task.company_id.is_(None))
    if mine:
        # личные задачи самого пользователя: админ видит и чужие, но это не «мои дела»
        query = query.where(Task.owner_id == user.id)
    if date_from:
        query = query.where(Task.due_date >= date_from)
    if date_to:
        query = query.where(Task.due_date <= date_to)
    if kinds:
        query = query.where(Task.kind.in_(kinds))
    if statuses:
        query = query.where(Task.status.in_(statuses))
    if missing_amount:
        query = query.where(Task.needs_amount.is_(True), Task.amount_kopecks.is_(None))
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = await db.execute(
        query.order_by(
            Task.due_date.desc() if newest_first else Task.due_date,
            func.lower(Company.name),
            Task.title,
            Task.part,
            Task.id,
        )
        .limit(limit)
        .offset(offset)
    )
    payer_ids = await _payer_ids(db, user)
    items = [_view(user, *row, payer_ids) for row in rows]
    await _mark_files(db, items)
    return items, total


async def _mark_files(db: AsyncSession, items: list) -> None:
    if not items:
        return
    with_files = set(
        await db.scalars(
            select(Attachment.task_id).where(Attachment.task_id.in_([item.id for item in items]))
        )
    )
    for item in items:
        item.has_files = item.id in with_files


async def read(db: AsyncSession, user: User, show_notices: bool, task_id: int):
    row = (await db.execute(_query(user, show_notices).where(Task.id == task_id))).first()
    if row is None:
        return None
    view = _view(user, *row, await _payer_ids(db, user))
    await _mark_files(db, [view])
    if user.role == Role.CLIENT:
        return view
    task = row[0]
    result = TaskDetail.model_validate(view.model_dump())
    if task.rule_code == NDS_RULE:
        parts = await db.scalars(
            select(Task)
            .where(
                Task.company_id == task.company_id,
                Task.rule_code == NDS_RULE,
                Task.period_key == task.period_key,
            )
            .order_by(Task.part)
        )
        result.nds_parts = [NdsPart.model_validate(part) for part in parts]
    return result


async def editable(db: AsyncSession, user: User, ids: set[int]) -> list[Task]:
    """Задачи из ids, которые пользователь вправе менять; строки блокируются."""
    return list(
        await db.scalars(
            select(Task)
            .where(Task.id.in_(ids), editable_task_condition(user))
            .order_by(Task.id)
            .with_for_update()
        )
    )


async def patch(db: AsyncSession, actor: User, task: Task, body: TaskPatch) -> None:
    sent = body.model_fields_set
    values = body.model_dump(exclude_unset=True)
    reset_due = values.pop("reset_due", False)
    if empty := [name for name, v in values.items() if v is None and name != "amount_kopecks"]:
        raise TaskError(f"Поле нельзя очистить: {', '.join(empty)}")
    locked = {"title", "description", "due_date", "reset_due", "client_visible"}
    if task.signature_id and sent & locked:
        raise TaskError("Это напоминание об ЭЦП: измените подпись в карточке компании")
    if task.demand_id and sent & (locked | {"amount_kopecks"}):
        raise TaskError("Это задача по требованию: измените само требование")
    if task.source != TaskSource.CUSTOM and sent & {"title", "description"}:
        raise TaskError("Название и описание задачи из налоговых правил менять нельзя")
    if values.get("amount_kopecks") is not None and task.kind not in AMOUNT_KINDS:
        raise TaskError("Сумма указывается только для платежей")
    if "status" in values and not status_allowed(task.kind, values["status"]):
        raise TaskError("Этот статус неприменим к задаче такого типа")
    if reset_due and "due_date" in values:
        raise TaskError("Укажите новый срок или вернуть срок по правилам, но не оба сразу")
    if task.company_id is None and values.get("client_visible"):
        raise TaskError("Личную задачу клиент видеть не может")

    changes = {}
    if reset_due:
        rule = "next_workday" if task.source == TaskSource.RULE else None
        if rule is None and task.recurring_reminder_id:
            rule = await _reminder_shift(db, task)
        values.pop("due_date", None)
        due = shift(task.original_due_date, rule or "none", await load_calendar(db))
        if task.due_date != due or task.due_overridden:
            changes["due_date"] = due.isoformat()
        task.due_date, task.due_overridden = due, False
    for name, value in values.items():
        if getattr(task, name) == value:
            continue
        if name == "status":
            _set_status(task, value, actor)
        elif name == "amount_kopecks":
            override_amount(task, value)
        else:
            setattr(task, name, value)
            if name == "due_date":
                task.due_overridden = True
                if task.source == TaskSource.CUSTOM and not task.recurring_reminder_id:
                    task.original_due_date = value
        journal = value.isoformat() if isinstance(value, date) else value
        changes[name] = None if name in NOT_JOURNALED else journal
    if changes:
        audit.record(db, actor.id, "task.update", "task", task.id, {"changes": changes})
    await db.commit()


async def _reminder_shift(db: AsyncSession, task: Task) -> str | None:
    reminder = await db.get(RecurringReminder, task.recurring_reminder_id)
    return reminder.shift_rule if reminder else None


async def bulk_status(
    db: AsyncSession, actor: User, tasks: list[Task], status: str
) -> tuple[int, int]:
    updated = 0
    for task in tasks:
        if task.status == status or not status_allowed(task.kind, status):
            continue
        _set_status(task, status, actor)
        audit.record(db, actor.id, "task.update", "task", task.id, {"changes": {"status": status}})
        updated += 1
    await db.commit()
    return updated, len(tasks) - updated


async def create(db: AsyncSession, actor: User, body: TaskCreate) -> Task:
    if body.amount_kopecks is not None and body.kind not in AMOUNT_KINDS:
        raise TaskError("Сумма указывается только для платежей")
    personal = body.company_id is None
    task = Task(
        **body.model_dump(exclude={"client_visible"}),
        owner_id=actor.id if personal else None,
        source=TaskSource.CUSTOM,
        original_due_date=body.due_date,
        needs_amount=body.kind == TaskKind.PAYMENT,
        client_visible=body.client_visible and not personal,
        status=TaskStatus.PLANNED,
    )
    db.add(task)
    await db.flush()
    audit.record(
        db,
        actor.id,
        "task.create",
        "task",
        task.id,
        {"company_id": body.company_id, "title": body.title},
    )
    await db.commit()
    return task


async def delete(db: AsyncSession, actor: User, task: Task) -> None:
    if task.signature_id:
        raise TaskError("Это напоминание об ЭЦП: удалите подпись в карточке компании")
    if task.demand_id:
        raise TaskError("Это задача по требованию: удалите само требование")
    if task.source != TaskSource.CUSTOM:
        raise TaskError("Задачу из налоговых правил удалить нельзя: отметьте «Не требуется»")
    if task.recurring_reminder_id:
        raise TaskError("Задача из напоминания: отметьте «Не требуется» или измените напоминание")
    audit.record(db, actor.id, "task.delete", "task", task.id, {"company_id": task.company_id})
    await db.delete(task)
    await db.commit()
