"""Команда и приглашения: администратор и главный бухгалтер.

Главных бухгалтеров приглашает и отключает только администратор.
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import Database, ManagerUser
from app.core.settings_store import get_settings
from app.models import Invite, InviteKind, Role, User
from app.schemas.auth import UserOut
from app.services import audit, invites
from app.services.telegram.link import bot_link

router = APIRouter(prefix="/admin")
TEAM = (Role.CHIEF, Role.ACCOUNTANT, Role.ASSISTANT)
ADMIN_ONLY = "Это может сделать только администратор"


class AccountantPatch(BaseModel):
    is_active: bool


class InviteIn(BaseModel):
    # Клиентов приглашают из карточки компании.
    kind: Literal["chief", "accountant", "assistant"] = "accountant"


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
async def accountants(_: ManagerUser, db: Database) -> list[UserOut]:
    """Сотрудники: главные бухгалтеры, бухгалтеры и помощники."""
    users = await db.scalars(select(User).where(User.role.in_(TEAM)).order_by(User.id))
    return [UserOut.model_validate(user) for user in users]


@router.patch("/accountants/{user_id}")
async def update_accountant(
    user_id: int, body: AccountantPatch, admin: ManagerUser, db: Database
) -> UserOut:
    user = await db.get(User, user_id)
    if user is None or user.role not in TEAM:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")
    if user.role == Role.CHIEF and admin.role != Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, ADMIN_ONLY)
    if user.is_active != body.is_active:
        user.is_active = body.is_active
        audit.record(
            db, admin.id, "accountant.update", "user", user.id, {"is_active": body.is_active}
        )
        await db.commit()
    return UserOut.model_validate(user)


@router.get("/invites")
async def list_invites(user: ManagerUser, db: Database) -> list[InviteOut]:
    kinds = [InviteKind.ACCOUNTANT, InviteKind.ASSISTANT]
    if user.role == Role.ADMIN:
        kinds.append(InviteKind.CHIEF)
    found = [invite for kind in kinds for invite in await invites.list_open(db, kind)]
    found.sort(key=lambda invite: invite.id, reverse=True)
    if not found:
        return []
    link = invite_link_base()
    return [invite_out(invite, link) for invite in found]


@router.post("/invites", status_code=status.HTTP_201_CREATED)
async def create_invite(body: InviteIn, admin: ManagerUser, db: Database) -> InviteOut:
    if body.kind == InviteKind.CHIEF and admin.role != Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, ADMIN_ONLY)
    link = invite_link_base()  # до записи в базу: без ссылки приглашение бесполезно
    invite = await invites.create(db, InviteKind(body.kind), admin)
    return invite_out(invite, link)


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(invite_id: int, admin: ManagerUser, db: Database) -> Response:
    invite = await db.get(Invite, invite_id)
    if invite is not None and invite.kind == InviteKind.CHIEF and admin.role != Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, ADMIN_ONLY)
    if not await invites.revoke(db, invite_id, admin):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Приглашение не найдено или уже не действует"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
