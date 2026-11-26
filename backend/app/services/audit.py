from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


def record(
    db: AsyncSession,
    user_id: int | None,
    action: str,
    entity: str,
    entity_id: object = None,
    payload: dict | None = None,
) -> None:
    """Добавляет запись в журнал. Фиксируется вместе с транзакцией вызывающего.

    В payload не должно быть секретов.
    """
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity=entity,
            entity_id=None if entity_id is None else str(entity_id),
            payload=payload,
        )
    )
