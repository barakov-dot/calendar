"""Проверка initData Telegram Mini App и выпуск JWT."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import parse_qsl

import jwt

INIT_DATA_MAX_AGE = timedelta(hours=24)
CLOCK_SKEW = timedelta(minutes=5)
# данные виджета передаются сразу после подтверждения входа
WIDGET_MAX_AGE = timedelta(minutes=10)
ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=30)
MIN_JWT_SECRET = 32
ALGORITHM = "HS256"

TokenType = Literal["access", "refresh"]


class AuthError(Exception):
    """Подпись, срок или формат не прошли проверку."""


def validate_init_data(init_data: str, bot_token: str, now: datetime | None = None) -> dict:
    """Возвращает объект user из initData после проверки подписи и срока."""
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        raise AuthError("неверный формат initData") from None
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise AuthError("повторяющиеся поля в initData")
    received = fields.pop("hash", "")
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected.encode(), received.encode()):
        raise AuthError("неверная подпись initData")

    now = now or datetime.now(UTC)
    try:
        issued = datetime.fromtimestamp(int(fields["auth_date"]), UTC)
        user = json.loads(fields["user"])
        user["id"] = int(user["id"])
    except (KeyError, ValueError, TypeError, OverflowError, OSError):
        raise AuthError("в initData нет пользователя или даты") from None
    if not -CLOCK_SKEW <= now - issued <= INIT_DATA_MAX_AGE:
        raise AuthError("initData устарели, откройте приложение заново")
    return user


def validate_widget_data(data: dict, bot_token: str, now: datetime | None = None) -> int:
    """Проверяет данные виджета «Войти через Telegram», возвращает telegram id."""
    fields = {key: str(value) for key, value in data.items() if value is not None}
    received = fields.pop("hash", "")
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hashlib.sha256(bot_token.encode()).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected.encode(), received.encode()):
        raise AuthError("неверная подпись Telegram")
    now = now or datetime.now(UTC)
    try:
        issued = datetime.fromtimestamp(int(fields["auth_date"]), UTC)
        telegram_id = int(fields["id"])
    except (KeyError, ValueError, OverflowError, OSError):
        raise AuthError("в ответе Telegram нет пользователя или даты") from None
    if not -CLOCK_SKEW <= now - issued <= WIDGET_MAX_AGE:
        raise AuthError("данные входа устарели, войдите ещё раз")
    return telegram_id


def create_token(user_id: int, kind: TokenType, secret: str, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    ttl = ACCESS_TTL if kind == "access" else REFRESH_TTL
    claims = {"sub": str(user_id), "type": kind, "iat": now, "exp": now + ttl}
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def read_token(token: str, kind: TokenType, secret: str) -> int:
    """Возвращает id пользователя. Тип токена обязателен: refresh не годится как access."""
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            options={"require": ["sub", "type", "exp"]},
        )
        if claims["type"] != kind:
            raise AuthError("неверный тип токена")
        return int(claims["sub"])
    except (jwt.InvalidTokenError, ValueError):
        raise AuthError("токен недействителен или просрочен") from None
