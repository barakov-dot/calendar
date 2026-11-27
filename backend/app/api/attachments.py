"""Файлы к платежам. Права проверяются в каждом запросе, недоступное отвечает 404.

Файл передаётся телом запроса, имя — в заголовке X-Filename (percent-encoding),
чтобы оно не попадало в логи вместе с адресом.
"""

from datetime import datetime
from urllib.parse import quote, unquote

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.api.deps import CurrentUser, Database
from app.services import attachments
from app.services.companies import person_name
from app.services.telegram.documents import SendError, send_document

router = APIRouter()


class AttachmentOut(BaseModel):
    id: int
    filename: str
    content_type: str
    size: int
    uploaded_by_name: str
    created_at: datetime
    can_delete: bool


class AttachmentList(BaseModel):
    items: list[AttachmentOut]
    can_upload: bool
    max_bytes: int = attachments.MAX_BYTES


def _failed(error: attachments.AttachmentError) -> HTTPException:
    return HTTPException(error.code, str(error))


async def _list(db: Database, user: CurrentUser, task_id: int) -> AttachmentList:
    try:
        can_upload, rows = await attachments.list_for(db, user, task_id)
    except attachments.AttachmentError as error:
        raise _failed(error) from None
    return AttachmentList(
        can_upload=can_upload,
        items=[
            AttachmentOut(
                id=item.id,
                filename=item.filename,
                content_type=item.content_type,
                size=item.size,
                uploaded_by_name=person_name(author),
                created_at=item.created_at,
                can_delete=can_delete,
            )
            for item, author, can_delete in rows
        ],
    )


@router.get("/tasks/{task_id}/attachments")
async def list_attachments(task_id: int, user: CurrentUser, db: Database) -> AttachmentList:
    return await _list(db, user, task_id)


async def _body(request: Request) -> bytes:
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > attachments.MAX_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Файл больше 10 МБ")
    return bytes(data)


@router.post("/tasks/{task_id}/attachments", status_code=status.HTTP_201_CREATED)
async def upload(task_id: int, request: Request, user: CurrentUser, db: Database) -> AttachmentList:
    try:
        # права проверяются до приёма файла
        await attachments.check_upload(db, user, task_id)
        data = await _body(request)
        name = unquote(request.headers.get("x-filename", ""))
        await attachments.add(db, user, task_id, name, data)
    except attachments.AttachmentError as error:
        raise _failed(error) from None
    return await _list(db, user, task_id)


@router.get("/attachments/{attachment_id}")
async def download(attachment_id: int, user: CurrentUser, db: Database) -> Response:
    try:
        item = await attachments.read(db, user, attachment_id)
    except attachments.AttachmentError as error:
        raise _failed(error) from None
    return Response(
        item.data,
        media_type=item.content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(item.filename)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.post("/attachments/{attachment_id}/send", status_code=status.HTTP_204_NO_CONTENT)
async def send(attachment_id: int, user: CurrentUser, db: Database) -> Response:
    """Присылает файл тому, кто просит, в чат с ботом."""
    try:
        item = await attachments.read(db, user, attachment_id)
        await send_document(user, item.data, item.filename)
    except attachments.AttachmentError as error:
        raise _failed(error) from None
    except SendError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(attachment_id: int, user: CurrentUser, db: Database) -> Response:
    try:
        await attachments.remove(db, user, attachment_id)
    except attachments.AttachmentError as error:
        raise _failed(error) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
