"""Бухгалтеры и приглашения. Только администратор."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import AdminUser, Database
from app.core.settings_store import get_settings
from app.models import Invite, InviteKind, Role, User
from app.schemas.auth import UserOut
from app.services import audit, invites
from app.services.telegram.link import bot_link

router = APIRouter(prefix="/admin")


class AccountantPatch(BaseModel):
    is_active: bool


class InviteIn(BaseModel):
    # Клиентов приглашают из карточки компании.
    kind: Literal["accountant"] = "accountant"


class InviteOut(BaseModel):
    id: int
    kind: str
    link: str
    created_at: datetime
    expires_at: datetime


def invite_link_base() -> str:
    link = bot_link(get_settings())
    if link is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Имя бота пока неизвестно: дождитесь подключения бота к Telegram",
        )
    return link


def invite_out(invite: Invite, link: str) -> InviteOut:
    return InviteOut(
        id=invite.id,
        kind=invite.kind,
        link=f"{link}?start={invites.DEEPLINK_PREFIX}{invite.token}",
        created_at=invite.created_at,
        expires_at=invite.expires_at,
    )


@router.get("/accountants")
async def accountants(_: AdminUser, db: Database) -> list[UserOut]:
    users = await db.scalars(select(User).where(User.role == Role.ACCOUNTANT).order_by(User.id))
    return [UserOut.model_validate(user) for user in users]


@router.patch("/accountants/{user_id}")
async def update_accountant(
    user_id: int, body: AccountantPatch, admin: AdminUser, db: Database
) -> UserOut:
    user = await db.get(User, user_id)
    if user is None or user.role != Role.ACCOUNTANT:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Бухгалтер не найден")
    if user.is_active != body.is_active:
        user.is_active = body.is_active
        audit.record(
            db, admin.id, "accountant.update", "user", user.id, {"is_active": body.is_active}
        )
        await db.commit()
    return UserOut.model_validate(user)


@router.get("/invites")
async def list_invites(_: AdminUser, db: Database) -> list[InviteOut]:
    found = await invites.list_open(db, InviteKind.ACCOUNTANT)
    if not found:
        return []
    link = invite_link_base()
    return [invite_out(invite, link) for invite in found]


@router.post("/invites", status_code=status.HTTP_201_CREATED)
async def create_invite(body: InviteIn, admin: AdminUser, db: Database) -> InviteOut:
    link = invite_link_base()  # до записи в базу: без ссылки приглашение бесполезно
    invite = await invites.create(db, InviteKind(body.kind), admin)
    return invite_out(invite, link)


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(invite_id: int, admin: AdminUser, db: Database) -> Response:
    if not await invites.revoke(db, invite_id, admin):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Приглашение не найдено или уже не действует"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
