from app.models import Task, TaskStatus

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
