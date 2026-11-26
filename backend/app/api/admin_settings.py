"""Настройки приложения. Только администратор. Секреты наружу не отдаются."""

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import AdminUser, AppConfig, Database
from app.core.settings_store import (
    MASK,
    AppSettings,
    SettingsError,
    get_store,
    masked_settings,
    parse_settings,
    parse_settings_text,
)
from app.services import audit
from app.services.dadata.client import DadataError, check_keys
from app.services.telegram.check import check_connection
from app.services.telegram.factory import ProxyConfigError, resolve_proxy
from app.services.telegram.link import bot_link
from app.services.telegram.status import read_status, status_path

router = APIRouter(prefix="/admin")


class SettingsOut(BaseModel):
    settings: dict[str, Any]
    file_error: str | None = None


class SettingsPatch(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    clear: list[str] = Field(default_factory=list)


class ProxyIn(BaseModel):
    enabled: bool = False
    host: str = ""
    port: int = 1080
    username: str = ""
    password: str = ""
    rdns: bool = True


class DadataIn(BaseModel):
    api_key: str = ""
    secret_key: str = ""


class CheckOut(BaseModel):
    ok: bool
    message: str


class BackupOut(BaseModel):
    name: str
    created_at: datetime | None
    valid: bool


def _out(settings: AppSettings) -> SettingsOut:
    return SettingsOut(settings=masked_settings(settings), file_error=get_store().last_error)


def _invalid(error: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))


@router.get("/settings")
async def read_settings(_: AdminUser) -> SettingsOut:
    store = get_store()
    store.reload()
    return _out(store.get())


@router.patch("/settings")
async def patch_settings(body: SettingsPatch, admin: AdminUser, db: Database) -> SettingsOut:
    try:
        settings, changed = await asyncio.to_thread(
            get_store().update_with_changes, body.settings, admin.id, body.clear
        )
    except SettingsError as error:
        raise _invalid(error) from None
    if changed:
        audit.record(db, admin.id, "settings.update", "settings", payload={"fields": changed})
        await db.commit()
    return _out(settings)


@router.post("/settings/test-proxy")
async def test_proxy(body: ProxyIn, _: AdminUser, config: AppConfig) -> CheckOut:
    saved = get_store().get().telegram.proxy
    proxy = body.model_dump()
    if body.password in ("", MASK):
        # Сохранённый пароль отправляется только туда, для чего он был сохранён.
        same = (body.host, body.port, body.username) == (saved.host, saved.port, saved.username)
        proxy["password"] = saved.password if same else ""
    try:
        candidate = parse_settings({"telegram": {"proxy": proxy}})
        resolved = resolve_proxy(candidate, config.telegram_proxy_url)
    except (SettingsError, ProxyConfigError) as error:
        raise _invalid(error) from None
    result = await check_connection(config, resolved)
    via = str(resolved) if resolved else "напрямую, без прокси"
    return CheckOut(ok=result.ok, message=f"{result.message}. Проверено: {via}")


@router.post("/settings/test-dadata")
async def test_dadata(body: DadataIn, _: AdminUser) -> CheckOut:
    saved = get_store().get().dadata

    def chosen(value: str, stored: str) -> str:
        return stored if value in ("", MASK) else value.strip()

    try:
        message = await check_keys(
            chosen(body.api_key, saved.api_key),
            chosen(body.secret_key, saved.secret_key),
            saved.timeout_seconds,
        )
    except DadataError as error:
        return CheckOut(ok=False, message=str(error))
    return CheckOut(ok=True, message=message)


@router.get("/settings/backups")
async def backups(_: AdminUser) -> list[BackupOut]:
    result = []
    for path in get_store().list_backups():
        try:
            created = datetime.strptime(path.stem, "settings-%Y%m%d-%H%M%S-%f").replace(tzinfo=UTC)
        except ValueError:
            created = None
        try:
            parse_settings_text(path.read_bytes())
            valid = True
        except (OSError, SettingsError):
            valid = False
        result.append(BackupOut(name=path.name, created_at=created, valid=valid))
    return result


@router.post("/settings/backups/{name}/restore")
async def restore_backup(name: str, admin: AdminUser, db: Database) -> SettingsOut:
    try:
        settings, changed = await asyncio.to_thread(get_store().restore, name, admin.id)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Резервная копия не найдена") from None
    except SettingsError as error:
        raise _invalid(error) from None
    payload = {"backup": name, "fields": changed}
    audit.record(db, admin.id, "settings.restore", "settings", payload=payload)
    await db.commit()
    return _out(settings)


@router.get("/bot-status")
async def bot_status(_: AdminUser, config: AppConfig) -> dict[str, Any]:
    data = read_status(status_path(config.settings_path))
    return data | {"link": bot_link(get_store().get())}
