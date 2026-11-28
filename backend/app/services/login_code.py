"""Вход на сайт по коду: человек вводит логин, бот присылает код на телефон.

Telegram на компьютере не нужен. По ответам сайта нельзя узнать, есть ли такой логин:
запрос записывается и для незнакомого, а пределы одинаковы для всех.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LoginCode, User
from app.services.users import can_sign_in

TTL = timedelta(minutes=5)
CODE_LENGTH = 6
MAX_ATTEMPTS = 5
# на один логин: не чаще раза в минуту и не больше стольких в час
REPEAT_AFTER = timedelta(minutes=1)
PER_HOUR = 5
# на всех вместе: перебор логинов не должен засыпать базу и людей
TOTAL_PER_HOUR = 200
DENY_PREFIX = "code-deny:"


class TooManyRequests(Exception):
    """Текст показывается пользователю."""


def normalize(login: str) -> str:
    return login.strip().lstrip("@").lower()


def _digest(secret: str, request_id: str, code: str) -> str:
    return hmac.new(secret.encode(), f"{request_id}:{code}".encode(), hashlib.sha256).hexdigest()


async def find_user(db: AsyncSession, key: str) -> User | None:
    """По логину, заданному администратором, иначе по @username, если он у одного человека."""
    user = await db.scalar(select(User).where(User.login == key))
    if user is None:
        found = list(
            await db.scalars(
                select(User)
                .where(func.lower(User.username) == key, User.is_active.is_(True))
                .limit(2)
            )
        )
        user = found[0] if len(found) == 1 else None
    reachable = can_sign_in(user) and not user.bot_blocked and user.telegram_id > 0
    return user if reachable else None


async def _check_limits(db: AsyncSession, key: str, now: datetime) -> None:
    recent = (
        select(func.count())
        .select_from(LoginCode)
        .where(LoginCode.created_at > now - timedelta(hours=1))
    )
    own = recent.where(LoginCode.login_key == key)
    if await db.scalar(own.where(LoginCode.created_at > now - REPEAT_AFTER)):
        raise TooManyRequests("Код уже запрошен. Повторить можно через минуту")
    if await db.scalar(own) >= PER_HOUR or await db.scalar(recent) >= TOTAL_PER_HOUR:
        raise TooManyRequests("Слишком много запросов кода. Повторите через час")


async def create(db: AsyncSession, secret: str, login: str) -> tuple[LoginCode, User | None, str]:
    """Новый запрос: (запись, кому отправить, код). Прежние коды этого логина отменяются."""
    key = normalize(login)
    now = datetime.now(UTC)
    await db.execute(delete(LoginCode).where(LoginCode.created_at < now - timedelta(days=1)))
    await _check_limits(db, key, now)
    user = await find_user(db, key)
    await db.execute(
        update(LoginCode)
        .where(LoginCode.login_key == key, LoginCode.consumed_at.is_(None))
        .values(consumed_at=now)
    )
    request_id = secrets.token_urlsafe(32)
    code = f"{secrets.randbelow(10**CODE_LENGTH):0{CODE_LENGTH}d}"
    row = LoginCode(
        request_id=request_id,
        login_key=key,
        user_id=user.id if user else None,
        code_hash=_digest(secret, request_id, code),
        expires_at=now + TTL,
        created_at=now,
    )
    db.add(row)
    await db.commit()
    return row, user, code


async def verify(db: AsyncSession, secret: str, request_id: str, code: str) -> User | None:
    """Пользователь, если код верен. Каждая проверка расходует попытку, код — одноразовый."""
    row = await db.scalar(
        select(LoginCode).where(LoginCode.request_id == request_id).with_for_update()
    )
    now = datetime.now(UTC)
    if (
        row is None
        or row.consumed_at is not None
        or row.expires_at <= now
        or row.attempts >= MAX_ATTEMPTS
    ):
        await db.rollback()
        return None
    row.attempts += 1
    correct = hmac.compare_digest(row.code_hash, _digest(secret, request_id, code))
    user = await db.get(User, row.user_id) if correct and row.user_id else None
    if user is not None:
        row.consumed_at = now
    await db.commit()
    return user if can_sign_in(user) else None


async def deny(db: AsyncSession, code_id: int, user_id: int) -> bool:
    """«Это не я»: код отменяет только тот, кому он отправлен."""
    result = await db.execute(
        update(LoginCode)
        .where(
            LoginCode.id == code_id,
            LoginCode.user_id == user_id,
            LoginCode.consumed_at.is_(None),
        )
        .values(consumed_at=datetime.now(UTC))
        .returning(LoginCode.id)
    )
    denied = result.first() is not None
    await db.commit()
    return denied
