"""Требования: сроки, задачи в календаре и файл документа.

У требования две задачи: подписать квитанцию о приёме и исполнить само требование.
Они видны в «Задачах» и календаре, а напоминания о них имеют свои сроки.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.core.permissions import accessible_company_ids_query, get_accessible_company
from app.models import (
    ChangedBy,
    Company,
    Demand,
    DemandStep,
    Notification,
    NotificationType,
    Task,
    TaskSource,
    TaskStatus,
    User,
)
from app.services import attachments, audit
from app.services.calendar.workdays import load_calendar
from app.services.demands.recognize import Found
from app.services.demands.types import Kind, add_workdays, get_book

NOT_FOUND = "Требование не найдено"


class DemandError(Exception):
    """Текст показывается пользователю. code — HTTP-статус."""

    def __init__(self, message: str, code: int = 422) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Terms:
    """Исходные даты; пустые receipt_date и response_date считаются сами."""

    knd: str
    doc_date: date
    sent_date: date | None = None
    receipt_date: date | None = None
    response_workdays: int | None = None
    response_date: date | None = None


@dataclass(frozen=True)
class Dates:
    sent: date
    receipt: date
    response: date | None


async def calculate(db: AsyncSession, terms: Terms) -> Dates:
    book = get_book()
    calendar = await load_calendar(db)
    sent = terms.sent_date or terms.doc_date
    receipt = terms.receipt_date or add_workdays(calendar, sent, book.receipt.workdays)
    workdays = terms.response_workdays or book.kind(terms.knd).response_workdays
    response = terms.response_date
    if response is None and workdays:
        response = add_workdays(calendar, receipt, workdays)
    return Dates(sent, receipt, response)


async def match_company(db: AsyncSession, user: User, found: Found) -> Company | None:
    """Первая по порядку в тексте организация из доступных пользователю."""
    if not found.inns:
        return None
    rows = await db.scalars(
        select(Company).where(
            Company.inn.in_(found.inns),
            Company.is_archived.is_(False),
            Company.id.in_(accessible_company_ids_query(user)),
        )
    )
    companies = {company.inn: company for company in rows}
    return next((companies[inn] for inn in found.inns if inn in companies), None)


async def get(db: AsyncSession, user: User, demand_id: int, lock: bool = False) -> Demand:
    """Требование доступной организации."""
    query = select(Demand).where(
        Demand.id == demand_id, Demand.company_id.in_(accessible_company_ids_query(user))
    )
    demand = await db.scalar(query.with_for_update() if lock else query)
    if demand is None:
        raise DemandError(NOT_FOUND, 404)
    return demand


async def steps(db: AsyncSession, demand_ids: list[int]) -> dict[tuple[int, str], Task]:
    rows = await db.scalars(select(Task).where(Task.demand_id.in_(demand_ids)))
    return {(task.demand_id, task.demand_step): task for task in rows}


def _titles(kind: Kind, demand: Demand) -> tuple[str, str]:
    number = f" № {demand.number}" if demand.number else ""
    return f"{kind.short}{number}", f"{kind.short}{number} от {demand.doc_date:%d.%m.%Y}"


async def _sync(db: AsyncSession, demand: Demand) -> None:
    """Приводит две задачи требования в соответствие с ним."""
    book = get_book()
    kind = book.kind(demand.knd)
    subject, period = _titles(kind, demand)
    existing = await steps(db, [demand.id])
    wanted = (
        (DemandStep.RECEIPT, "Подписать квитанцию о приёме", demand.receipt_date, "other"),
        (DemandStep.RESPONSE, kind.action, demand.response_date, kind.task_kind),
    )
    for step, action, due, task_kind in wanted:
        task = existing.get((demand.id, step))
        if task is None:
            task = Task(
                company_id=demand.company_id,
                demand_id=demand.id,
                demand_step=step,
                source=TaskSource.CUSTOM,
                due_date=due,
                original_due_date=due,
                status=TaskStatus.PLANNED,
                client_visible=False,
                title="",
                kind=task_kind,
            )
            db.add(task)
        elif task.due_date != due:
            task.due_date = task.original_due_date = due
            # напоминания о новом сроке начинаются заново
            await db.execute(
                delete(Notification).where(
                    Notification.task_id == task.id, Notification.type == NotificationType.DEMAND
                )
            )
        if task.status == TaskStatus.PLANNED:
            task.kind = task_kind
        task.title = f"{action}: {subject}"
        task.action_title = action
        task.period_label = period
        task.description = demand.note
        source = book.receipt.source if step == DemandStep.RECEIPT else kind.source
        task.source_ref = source
        if step == DemandStep.RESPONSE:
            task.amount_kopecks = demand.amount_kopecks


async def save(
    db: AsyncSession,
    actor: User,
    demand: Demand | None,
    values: dict,
    receipt_done: bool = False,
) -> Demand:
    """Создаёт или изменяет требование вместе с задачами."""
    company = await get_accessible_company(db, actor, values["company_id"])
    if company is None:
        raise DemandError("Компания не найдена", 404)
    if demand is None and company.is_archived:
        raise DemandError("Компания в архиве", 409)
    if demand is not None and demand.company_id != company.id:
        raise DemandError("Организацию изменить нельзя: удалите требование и загрузите заново")
    terms = Terms(
        knd=values["knd"],
        doc_date=values["doc_date"],
        sent_date=values["sent_date"],
        receipt_date=values["receipt_date"],
        response_workdays=values["response_workdays"],
        response_date=values["response_date"],
    )
    dates = await calculate(db, terms)
    if dates.response is None:
        label = get_book().kind(terms.knd).response_label.lower()
        raise DemandError(f"Укажите: {label}")
    if dates.sent < terms.doc_date:
        raise DemandError("Дата отправки раньше даты документа")
    if dates.receipt < dates.sent or dates.response < terms.doc_date:
        raise DemandError("Проверьте даты: срок раньше самого документа")
    if values["number"]:
        same = await db.scalar(
            select(Demand.id).where(
                Demand.company_id == company.id,
                Demand.knd == values["knd"],
                Demand.number == values["number"],
                Demand.doc_date == values["doc_date"],
                Demand.id != (demand.id if demand else 0),
            )
        )
        if same is not None:
            raise DemandError("Это требование уже загружено", 409)

    created = demand is None
    if demand is None:
        demand = Demand(company_id=company.id, created_by=actor.id)
        db.add(demand)
    for name in ("knd", "number", "doc_date", "response_workdays", "amount_kopecks", "note"):
        setattr(demand, name, values[name])
    demand.sent_date = dates.sent
    demand.receipt_date = dates.receipt
    demand.response_date = dates.response
    demand.receipt_set = values["receipt_date"] is not None
    demand.response_set = values["response_date"] is not None
    await db.flush()
    await _sync(db, demand)
    await db.flush()
    if receipt_done:
        task = (await steps(db, [demand.id]))[(demand.id, DemandStep.RECEIPT)]
        if task.status == TaskStatus.PLANNED:
            task.status = TaskStatus.DONE
            task.status_changed_by = actor.id
            task.status_changed_by_role = ChangedBy(actor.role)
            task.status_changed_at = datetime.now(UTC)
    # комментарий и номер могут содержать персональные данные, в журнал не пишутся
    audit.record(
        db,
        actor.id,
        "demand.create" if created else "demand.update",
        "demand",
        demand.id,
        {
            "company_id": company.id,
            "knd": demand.knd,
            "receipt_date": dates.receipt.isoformat(),
            "response_date": dates.response.isoformat(),
        },
    )
    await db.commit()
    return demand


async def remove(db: AsyncSession, actor: User, demand: Demand) -> None:
    audit.record(
        db, actor.id, "demand.delete", "demand", demand.id, {"company_id": demand.company_id}
    )
    await db.delete(demand)  # задачи и уведомления удаляются каскадом
    await db.commit()


async def put_file(db: AsyncSession, actor: User, demand: Demand, name: str, data: bytes) -> None:
    if not data:
        raise DemandError("Файл пустой")
    if len(data) > attachments.MAX_BYTES:
        raise DemandError("Файл больше 10 МБ", 413)
    content_type = attachments.detect_type(data)
    if content_type is None:
        raise DemandError("Подходят только PDF и фотографии (JPG, PNG, WEBP, HEIC)", 415)
    demand.filename = attachments.clean_name(name, content_type)
    demand.content_type = content_type
    demand.data = data
    audit.record(db, actor.id, "demand.file", "demand", demand.id)
    await db.commit()


async def read_file(db: AsyncSession, user: User, demand_id: int) -> Demand:
    await get(db, user, demand_id)
    demand = await db.get(Demand, demand_id, options=[undefer(Demand.data)], populate_existing=True)
    if demand is None or demand.data is None:
        raise DemandError("Файл не найден", 404)
    return demand
