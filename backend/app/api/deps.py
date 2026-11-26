"""Общие зависимости: база, секреты, текущий пользователь, проверка роли."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import Config, get_config
from app.core.db import get_session
from app.models import Role, User
from app.services.users import can_sign_in

Database = Annotated[AsyncSession, Depends(get_session)]
AppConfig = Annotated[Config, Depends(get_config)]

bearer = HTTPBearer(auto_error=False)


def jwt_secret(config: AppConfig) -> str:
    secret = config.jwt_secret.get_secret_value() if config.jwt_secret else ""
    if len(secret) < security.MIN_JWT_SECRET:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"Вход не настроен: задайте в .env JWT_SECRET не короче "
            f"{security.MIN_JWT_SECRET} символов и перезапустите сервис",
        )
    return secret


JwtSecret = Annotated[str, Depends(jwt_secret)]


def unauthorized(detail: str = "Требуется вход") -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


async def current_user(
    db: Database,
    secret: JwtSecret,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if credentials is None:
        raise unauthorized()
    try:
        user_id = security.read_token(credentials.credentials, "access", secret)
    except security.AuthError:
        raise unauthorized() from None
    # Роль и активность берутся из базы, а не из токена: отзыв доступа действует сразу.
    user = await db.get(User, user_id)
    if not can_sign_in(user):
        raise unauthorized()
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_role(*roles: Role) -> Callable:
    async def check(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")
        return user

    return check


AdminUser = Annotated[User, Depends(require_role(Role.ADMIN))]
