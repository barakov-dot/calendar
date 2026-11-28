"""Обновление перечня форм организации и задач по ним."""

import asyncio
import logging
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings_store import AppSettings
from app.models import Company, RosstatForm, Task, TaskKind, TaskSource, TaskStatus
from app.services import tasks
from app.services.rosstat.client import Client, RosstatError, Unavailable
from app.services.rosstat.parse import Form, parse_form
from app.services.task_state import is_untouched

logger = logging.getLogger(__name__)

# пауза между организациями: сервис государственный и общий
PAUSE_SECONDS = 2
FIELDS = (
    "index",
    "name",
    "okud",
    "periodicity",
    "period",
    "deadline",
    "due_date",
    "comment",
)


def _fill_task(task: Task, form: Form) -> None:
    label = form.index or form.okud
    period = ""
    if form.period:
        starts = form.period.lower().startswith("за ")
        period = f" {form.period}" if starts else f" за {form.period}"
    task.title = f"Росстат: форма {label}{period}"[:500]
    task.action_title = f"Сдать в Росстат форму {label}"[:200]
    task.period_label = form.period[:200]
    task.description = " ".join(filter(None, (form.name, form.comment)))
    task.source_ref = "Росстат, websbor.rosstat.gov.ru"


async def apply(db: AsyncSession, company: Company, found: list[Form], current: date) -> None:
    """Приводит формы и задачи компании в соответствие с ответом Росстата."""
    existing = {
        row.key: row
        for row in await db.scalars(select(RosstatForm).where(RosstatForm.company_id == company.id))
    }
    rows = await db.scalars(
        select(Task)
        .join(RosstatForm, RosstatForm.id == Task.rosstat_form_id)
        .where(RosstatForm.company_id == company.id)
    )
    linked = {task.rosstat_form_id: task for task in rows}
    wanted = {form.key: form for form in found}

    for key, form in wanted.items():
        row = existing.get(key)
        if row is None:
            row = RosstatForm(company_id=company.id, key=key)
            db.add(row)
        for name in FIELDS:
            setattr(row, name, getattr(form, name))
        await db.flush()
        task = linked.get(row.id)
        if form.due_date is None:
            continue
        if task is None:
            task = Task(
                company_id=company.id,
                rosstat_form_id=row.id,
                source=TaskSource.CUSTOM,
                kind=TaskKind.REPORT,
                status=TaskStatus.PLANNED,
                client_visible=False,
                due_date=form.due_date,
                original_due_date=form.due_date,
                title="",
            )
            db.add(task)
        elif not task.due_overridden:
            task.due_date = form.due_date
        task.original_due_date = form.due_date
        _fill_task(task, form)

    # Формы больше нет в перечне: убираем только то, что ещё впереди и никем не тронуто.
    for key, row in existing.items():
        if key in wanted or row.due_date is None or row.due_date < current:
            continue
        task = linked.get(row.id)
        if task is None or is_untouched(task):
            await db.delete(row)  # задача удаляется каскадом


async def refresh_company(db: AsyncSession, client: Client, company: Company) -> None:
    """Ищет организацию по ИНН и обновляет её формы. Ошибка записывается в компанию."""
    company.rosstat_checked_at = datetime.now(UTC)
    try:
        organization = await client.organization(company.inn)
        if organization is None:
            raise RosstatError("Организации с таким ИНН нет в статрегистре Росстата")
        raw = await client.forms(organization["id"])
    except RosstatError as error:
        company.rosstat_error = str(error)
        await db.commit()
        raise
    company.rosstat_okpo = str(organization.get("okpo") or "")[:14]
    company.rosstat_error = ""
    found = [form for item in raw if (form := parse_form(item)) is not None]
    await apply(db, company, found, tasks.today())
    await db.commit()


def due_since(settings: AppSettings, now: datetime) -> datetime:
    """Момент последнего планового запуска: проверенное раньше пора обновить."""
    zone = ZoneInfo(settings.company.timezone)
    local = now.astimezone(zone)
    hours, minutes = map(int, settings.rosstat.search_time.split(":"))
    planned = datetime.combine(local.date(), time(hours, minutes), zone)
    if planned > local:
        planned = datetime.combine(date.fromordinal(local.toordinal() - 1), planned.time(), zone)
    return planned


async def run_due(
    db: AsyncSession,
    settings: AppSettings,
    now: datetime,
    client: Client,
    pause: float = PAUSE_SECONDS,
) -> int:
    """Проверяет организации, которые пора обновить. Возвращает их число.

    Новые организации проверяются сразу. Без связи с Росстатом обход прерывается
    (Unavailable): остальные остаются в очереди.
    """
    ids = list(
        await db.scalars(
            select(Company.id)
            .where(
                Company.is_archived.is_(False),
                or_(
                    Company.rosstat_checked_at.is_(None),
                    Company.rosstat_checked_at < due_since(settings, now),
                ),
            )
            .order_by(Company.id)
        )
    )
    done = 0
    for company_id in ids:
        company = await db.get(Company, company_id, populate_existing=True)
        try:
            await refresh_company(db, client, company)
        except Unavailable:
            # эту организацию тоже нужно проверить, когда связь вернётся
            await db.execute(
                update(Company).where(Company.id == company_id).values(rosstat_checked_at=None)
            )
            await db.commit()
            raise
        except RosstatError as error:
            logger.warning("Росстат, компания %s: %s", company_id, error)
        done += 1
        await asyncio.sleep(pause)
    return done
