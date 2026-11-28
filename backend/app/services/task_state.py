from sqlalchemy import ColumnElement, and_, func, or_

from app.models import Company, Task, TaskSource, TaskStatus

# Аванс и зарплата: клиенту о них напоминают только в день выплаты.
PAYDAY_RULES = ("salary_advance", "salary_payment")


def is_untouched(task: Task, filled_amount: int | None = None) -> bool:
    """Задачу никто не менял: автоматика вправе её удалить.

    filled_amount — сумма, которую подставила сама автоматика (из напоминания).
    """
    return (
        task.status == TaskStatus.PLANNED
        and task.status_changed_at is None
        and task.amount_kopecks in (None, filled_amount)
        and not task.amount_overridden
        and not task.due_overridden
        and not task.comment
        and not task.client_note
    )


def before_start(task: Task, company: Company | None) -> bool:
    """Срок по правилам или перечню Росстата раньше начала ведения календаря организации.

    Такая задача остаётся и меняется как обычно, но не считается пропущенной и не
    напоминает о себе. Задачи, заведённые людьми, это не затрагивает.
    """
    return (
        company is not None
        and company.calendar_start is not None
        and (task.source == TaskSource.RULE or task.rosstat_form_id is not None)
        and task.due_date < company.calendar_start
    )


def before_start_condition() -> ColumnElement[bool]:
    """То же для запроса, в котором есть Company (можно через outerjoin)."""
    generated = or_(Task.source == TaskSource.RULE, Task.rosstat_form_id.is_not(None))
    return func.coalesce(and_(generated, Task.due_date < Company.calendar_start), False)
