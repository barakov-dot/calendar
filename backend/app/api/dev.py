"""Вход без Telegram. Роутер подключается только при APP_ENV=dev."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.auth import issue_tokens
from app.api.deps import Database, JwtSecret
from app.models import User
from app.schemas.auth import DevLoginIn, Tokens, UserOut

router = APIRouter()


@router.get("/auth/dev-users")
async def dev_users(db: Database) -> list[UserOut]:
    users = await db.scalars(select(User).order_by(User.id))
    return [UserOut.model_validate(user) for user in users]


@router.post("/auth/dev-login")
async def dev_login(body: DevLoginIn, db: Database, secret: JwtSecret) -> Tokens:
    user = await db.get(User, body.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден или отключён")
    if user.pd_consent_at is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Пользователь ещё не дал согласие")
    return issue_tokens(user, secret)
