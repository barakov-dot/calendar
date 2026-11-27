"""Иконка сайта: видна всем (в том числе до входа), меняет администратор."""

import asyncio

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.api.deps import AdminUser, Database
from app.services import audit, site_icon

router = APIRouter()

HEADERS = {
    # после замены браузер берёт новую картинку
    "Cache-Control": "no-cache",
    "X-Content-Type-Options": "nosniff",
    # в SVG бывают скрипты: при открытии по прямой ссылке они не выполняются
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
}


class IconOut(BaseModel):
    content_type: str


@router.get("/site-icon")
async def read() -> Response:
    found = site_icon.current()
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Иконка не загружена")
    path, content_type = found
    return FileResponse(path, media_type=content_type, headers=HEADERS)


@router.post("/admin/site-icon")
async def upload(request: Request, admin: AdminUser, db: Database) -> IconOut:
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > site_icon.MAX_BYTES:
            break  # сохранение откажет с понятным объяснением
    try:
        content_type = await asyncio.to_thread(site_icon.save, bytes(data))
    except site_icon.IconError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    audit.record(db, admin.id, "site_icon.update", "settings")
    await db.commit()
    return IconOut(content_type=content_type)


@router.delete("/admin/site-icon", status_code=status.HTTP_204_NO_CONTENT)
async def delete(admin: AdminUser, db: Database) -> Response:
    if await asyncio.to_thread(site_icon.remove):
        audit.record(db, admin.id, "site_icon.delete", "settings")
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
