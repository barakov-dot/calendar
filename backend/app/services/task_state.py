from sqlalchemy import ColumnElement, and_, func

from app.models import Company, Task, TaskSource, TaskStatus

# Аванс и зарплата: клиенту о них напоминают только в день выплаты.
PAYDAY_RULES = ("salary_advance", "salary_payment")


def is_untouched(task: Task) -> bool:
    """Задачу никто не менял: автоматика вправе её удалить."""
    return (
        task.status == TaskStatus.PLANNED
        and task.status_changed_at is None
        and task.amount_kopecks is None
        and not task.amount_overridden
        and not task.due_overridden
        and not task.comment
        and not task.client_note
    )


def before_start(task: Task, company: Company | None) -> bool:
    """Срок по налоговым правилам раньше начала ведения календаря этой организации.

    Такая задача остаётся и меняется как обычно, но не считается пропущенной и не
    напоминает о себе. Задачи, заведённые людьми, это не затрагивает.
    """
    return (
        company is not None
        and company.calendar_start is not None
        and task.source == TaskSource.RULE
        and task.due_date < company.calendar_start
    )


def before_start_condition() -> ColumnElement[bool]:
    """То же для запроса, в котором есть Company (можно через outerjoin)."""
    return func.coalesce(
        and_(Task.source == TaskSource.RULE, Task.due_date < Company.calendar_start), False
    )
