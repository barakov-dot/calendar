"""Электронные подписи. У каждой есть задача со сроком окончания действия:
она видна в календаре, а напоминания о ней ставит планировщик."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification, Signature, Task, TaskKind, TaskSource, TaskStatus, User
from app.services import audit

DESCRIPTION = "Получите новую электронную подпись заранее, затем укажите её срок в карточке."


def title(holder: str) -> str:
    return f"Истекает ЭЦП: {holder}"


async def _task(db: AsyncSession, signature_id: int) -> Task | None:
    return await db.scalar(select(Task).where(Task.signature_id == signature_id).with_for_update())


async def _sync(db: AsyncSession, signature: Signature) -> None:
    task = await _task(db, signature.id)
    if task is None:
        task = Task(
            company_id=signature.company_id,
            signature_id=signature.id,
            source=TaskSource.CUSTOM,
            kind=TaskKind.OTHER,
            title="",
            description=DESCRIPTION,
            due_date=signature.expires_on,
            original_due_date=signature.expires_on,
            status=TaskStatus.PLANNED,
        )
        db.add(task)
    elif task.due_date != signature.expires_on:
        # подпись продлили: задача снова открыта, напоминания начинаются заново
        task.due_date = task.original_due_date = signature.expires_on
        task.status = TaskStatus.PLANNED
        task.status_changed_by = task.status_changed_by_role = task.status_changed_at = None
        await db.execute(delete(Notification).where(Notification.task_id == task.id))
    task.title = title(signature.holder)
    task.client_visible = signature.notify_client


async def list_for(db: AsyncSession, company_id: int) -> list[Signature]:
    return list(
        await db.scalars(
            select(Signature)
            .where(Signature.company_id == company_id)
            .order_by(Signature.expires_on, Signature.id)
        )
    )


async def save(db: AsyncSession, actor: User, signature: Signature, values: dict) -> Signature:
    """Создаёт или изменяет подпись вместе с её задачей."""
    created = signature.id is None
    for name, value in values.items():
        setattr(signature, name, value)
    db.add(signature)
    await db.flush()
    await _sync(db, signature)
    action = "signature.create" if created else "signature.update"
    # имя владельца — персональные данные, в журнал не пишется
    audit.record(
        db,
        actor.id,
        action,
        "signature",
        signature.id,
        {"company_id": signature.company_id, "expires_on": signature.expires_on.isoformat()},
    )
    await db.commit()
    return signature


async def remove(db: AsyncSession, actor: User, signature: Signature) -> None:
    audit.record(
        db,
        actor.id,
        "signature.delete",
        "signature",
        signature.id,
        {"company_id": signature.company_id},
    )
    await db.delete(signature)  # задача и её уведомления удаляются каскадом
    await db.commit()
