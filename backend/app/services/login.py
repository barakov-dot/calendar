"""Вход на сайт через бота: одноразовый nonce и опрос из браузера."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LoginRequest

LOGIN_TTL = timedelta(minutes=5)
MAX_PENDING = 500
DEEPLINK_PREFIX = "login_"


class TooManyRequests(Exception):
    pass


def comparison_code(nonce: str) -> str:
    """Код, который пользователь сверяет на сайте и в боте перед подтверждением."""
    number = int.from_bytes(hashlib.sha256(nonce.encode()).digest()[:4])
    return f"{number % 10000:04d}"


async def create_request(db: AsyncSession) -> LoginRequest:
    now = datetime.now(UTC)
    await db.execute(delete(LoginRequest).where(LoginRequest.expires_at < now))
    if await db.scalar(select(func.count()).select_from(LoginRequest)) >= MAX_PENDING:
        await db.commit()
        raise TooManyRequests
    request = LoginRequest(nonce=secrets.token_urlsafe(32), expires_at=now + LOGIN_TTL)
    db.add(request)
    await db.commit()
    return request


async def find_active(db: AsyncSession, nonce: str) -> LoginRequest | None:
    """Запрос, который ещё можно подтвердить или забрать."""
    request = await db.get(LoginRequest, nonce)
    if request is None or request.consumed_at or request.expires_at <= datetime.now(UTC):
        return None
    return request


async def confirm(db: AsyncSession, nonce: str, telegram_id: int) -> bool:
    """Подтверждает вход. Одним запросом, поэтому подтвердить можно только один раз."""
    now = datetime.now(UTC)
    result = await db.execute(
        update(LoginRequest)
        .where(
            LoginRequest.nonce == nonce,
            LoginRequest.confirmed_at.is_(None),
            LoginRequest.consumed_at.is_(None),
            LoginRequest.expires_at > now,
        )
        .values(confirmed_at=now, telegram_id=telegram_id)
        .returning(LoginRequest.nonce)
    )
    confirmed = result.first() is not None
    await db.commit()
    return confirmed


async def consume(db: AsyncSession, nonce: str) -> int | None:
    """Забирает подтверждённый вход ровно один раз и возвращает telegram_id."""
    now = datetime.now(UTC)
    result = await db.execute(
        update(LoginRequest)
        .where(
            LoginRequest.nonce == nonce,
            LoginRequest.confirmed_at.is_not(None),
            LoginRequest.consumed_at.is_(None),
            LoginRequest.expires_at > now,
        )
        .values(consumed_at=now)
        .returning(LoginRequest.telegram_id)
    )
    row = result.first()
    await db.commit()
    return None if row is None else row[0]
