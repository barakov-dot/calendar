from datetime import date

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification, NotificationStatus


async def enqueue(
    db: AsyncSession,
    user_id: int,
    kind: str,
    scheduled_for: date,
    task_id: int | None = None,
    again: bool = False,
    note: str = "",
) -> None:
    """Ставит уведомление в очередь. Дубликат пропускается.

    again — повторить уже отправленное (клиент отметил оплату ещё раз).
    """
    statement = insert(Notification).values(
        user_id=user_id, task_id=task_id, type=kind, scheduled_for=scheduled_for, note=note
    )
    if again:
        statement = statement.on_conflict_do_update(
            constraint="uq_notifications_log_key",
            set_={
                "status": NotificationStatus.PENDING,
                "attempts": 0,
                "next_attempt_at": None,
                "error": "",
                "note": note,
            },
        )
    else:
        statement = statement.on_conflict_do_nothing(constraint="uq_notifications_log_key")
    await db.execute(statement)
