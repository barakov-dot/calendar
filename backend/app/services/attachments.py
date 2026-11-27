"""Файлы к платежам: платёжки от клиента и бухгалтера."""

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.core.permissions import editable_task_condition, visible_task_condition
from app.core.settings_store import get_settings
from app.models import (
    Attachment,
    NotificationType,
    Role,
    Task,
    TaskKind,
    TaskStatus,
    User,
)
from app.services import audit, payments, tasks
from app.services.notify.queue import enqueue

MAX_BYTES = 10 * 1024 * 1024
MAX_PER_TASK = 5
EXTENSIONS = {
    "application/pdf": ("pdf",),
    "image/jpeg": ("jpg", "jpeg"),
    "image/png": ("png",),
    "image/webp": ("webp",),
    "image/heic": ("heic", "heif"),
}
NOT_FOUND = "Файл не найден"


class AttachmentError(Exception):
    """Текст показывается пользователю. code — HTTP-статус."""

    def __init__(self, message: str, code: int = 422) -> None:
        super().__init__(message)
        self.code = code


def detect_type(data: bytes) -> str | None:
    """Тип по содержимому: имени и заголовкам запроса не доверяем."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"mif1", b"heif"):
        return "image/heic"
    return None


def clean_name(name: str, content_type: str) -> str:
    """Имя без пути и служебных символов, с расширением по содержимому."""
    name = re.split(r"[\\/]", name)[-1]
    name = "".join(char for char in name if char.isprintable() and char not in '"<>:|?*')
    stem, dot, extension = name.strip(" .").rpartition(".")
    if not dot:
        stem, extension = extension, ""
    allowed = EXTENSIONS[content_type]
    extension = extension.lower() if extension.lower() in allowed else allowed[0]
    return f"{stem[:150].strip() or 'файл'}.{extension}"


async def _visible_task(db: AsyncSession, user: User, task_id: int, lock: bool = False) -> Task:
    show_notices = get_settings().tasks.show_notices_to_clients
    query = select(Task).where(Task.id == task_id, visible_task_condition(user, show_notices))
    task = await db.scalar(query.with_for_update() if lock else query)
    if task is None:
        raise AttachmentError("Задача не найдена", 404)
    return task


async def may_edit(db: AsyncSession, user: User, task: Task) -> bool:
    """Вправе прикладывать файлы: сотрудник с правом изменения или клиент, платящий сам."""
    if task.kind != TaskKind.PAYMENT or task.status == TaskStatus.NOT_REQUIRED:
        return False
    if user.role == Role.CLIENT:
        return task.company_id in await payments.payer_company_ids(db, user)
    if user.role not in (Role.ADMIN, Role.ACCOUNTANT):
        return False
    found = await db.scalar(
        select(Task.id).where(Task.id == task.id, editable_task_condition(user))
    )
    return found is not None


def may_delete(user: User, attachment: Attachment, can_edit: bool, now: datetime) -> bool:
    if not can_edit:
        return False
    if user.role != Role.CLIENT:
        return True
    hours = get_settings().tasks.client_can_unmark_own_paid_hours
    return attachment.uploaded_by == user.id and now - attachment.created_at <= timedelta(
        hours=hours
    )


async def list_for(
    db: AsyncSession, user: User, task_id: int
) -> tuple[bool, list[tuple[Attachment, User, bool]]]:
    """(можно ли добавить, [(файл, кто приложил, можно ли удалить)])."""
    task = await _visible_task(db, user, task_id)
    can_edit = await may_edit(db, user, task)
    rows = await db.execute(
        select(Attachment, User)
        .join(User, User.id == Attachment.uploaded_by)
        .where(Attachment.task_id == task_id)
        .order_by(Attachment.id)
    )
    now = datetime.now(UTC)
    found = [(item, author, may_delete(user, item, can_edit, now)) for item, author in rows]
    return can_edit and len(found) < MAX_PER_TASK, found


async def check_upload(db: AsyncSession, user: User, task_id: int, lock: bool = False) -> Task:
    """Проверка до чтения тела запроса и ещё раз, с блокировкой задачи, при записи."""
    task = await _visible_task(db, user, task_id, lock)
    if not await may_edit(db, user, task):
        raise AttachmentError("Приложить файл к этой задаче нельзя", 403)
    count = await db.scalar(
        select(func.count()).select_from(Attachment).where(Attachment.task_id == task_id)
    )
    if count >= MAX_PER_TASK:
        raise AttachmentError(f"К задаче можно приложить не больше {MAX_PER_TASK} файлов")
    return task


async def add(db: AsyncSession, user: User, task_id: int, name: str, data: bytes) -> Attachment:
    if not data:
        raise AttachmentError("Файл пустой")
    if len(data) > MAX_BYTES:
        raise AttachmentError("Файл больше 10 МБ", 413)
    content_type = detect_type(data)
    if content_type is None:
        raise AttachmentError("Подходят только PDF и фотографии (JPG, PNG, WEBP, HEIC)", 415)
    task = await check_upload(db, user, task_id, lock=True)
    attachment = Attachment(
        task_id=task.id,
        uploaded_by=user.id,
        filename=clean_name(name, content_type),
        content_type=content_type,
        size=len(data),
        data=data,
    )
    db.add(attachment)
    await db.flush()
    # имя файла может содержать персональные данные, в журнал не пишется
    audit.record(db, user.id, "attachment.add", "task", task.id, {"attachment_id": attachment.id})
    if user.role == Role.CLIENT:
        for recipient in await payments.responsible(db, task.company_id):
            await enqueue(
                db,
                recipient.id,
                NotificationType.ATTACHMENT,
                tasks.today(),
                task.id,
                again=True,
            )
    await db.commit()
    return attachment


async def read(db: AsyncSession, user: User, attachment_id: int) -> Attachment:
    """Файл с содержимым, если пользователь вправе видеть его задачу."""
    attachment = await db.get(Attachment, attachment_id, options=[undefer(Attachment.data)])
    if attachment is None:
        raise AttachmentError(NOT_FOUND, 404)
    try:
        await _visible_task(db, user, attachment.task_id)
    except AttachmentError:
        raise AttachmentError(NOT_FOUND, 404) from None
    return attachment


async def remove(db: AsyncSession, user: User, attachment_id: int) -> None:
    attachment = await db.get(Attachment, attachment_id)
    if attachment is None:
        raise AttachmentError(NOT_FOUND, 404)
    try:
        task = await _visible_task(db, user, attachment.task_id, lock=True)
    except AttachmentError:
        raise AttachmentError(NOT_FOUND, 404) from None
    if not may_delete(user, attachment, await may_edit(db, user, task), datetime.now(UTC)):
        raise AttachmentError("Удалить этот файл нельзя", 403)
    audit.record(
        db, user.id, "attachment.delete", "task", task.id, {"attachment_id": attachment.id}
    )
    await db.delete(attachment)
    await db.commit()
