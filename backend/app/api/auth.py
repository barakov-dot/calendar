from fastapi import APIRouter, HTTPException, status

from app.api.deps import AppConfig, CurrentUser, Database, JwtSecret, unauthorized
from app.core import security
from app.core.settings_store import get_settings
from app.models import User
from app.schemas.auth import InitDataIn, LoginRequestOut, PollOut, RefreshIn, Tokens, UserOut
from app.services import login
from app.services.telegram.link import bot_link
from app.services.users import can_sign_in, get_by_telegram_id

router = APIRouter()

INVITE_ONLY = "Доступ по приглашению"
NEEDS_CONSENT = "Отправьте боту /start и дайте согласие на обработку персональных данных"


def issue_tokens(user: User, secret: str) -> Tokens:
    return Tokens(
        access_token=security.create_token(user.id, "access", secret),
        refresh_token=security.create_token(user.id, "refresh", secret),
    )


def ensure_allowed(user: User | None) -> User:
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, INVITE_ONLY)
    if not can_sign_in(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, NEEDS_CONSENT)
    return user


@router.post("/auth/telegram-webapp")
async def telegram_webapp(
    body: InitDataIn, db: Database, config: AppConfig, secret: JwtSecret
) -> Tokens:
    if config.bot_token is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "BOT_TOKEN не задан")
    try:
        telegram_user = security.validate_init_data(
            body.init_data, config.bot_token.get_secret_value()
        )
    except security.AuthError as error:
        raise unauthorized(str(error)) from None
    user = ensure_allowed(await get_by_telegram_id(db, telegram_user["id"]))
    return issue_tokens(user, secret)


@router.post("/auth/login-request")
async def login_request(db: Database, secret: JwtSecret) -> LoginRequestOut:
    link = bot_link(get_settings())
    if link is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Имя бота пока неизвестно: дождитесь подключения бота к Telegram",
        )
    try:
        request = await login.create_request(db)
    except login.TooManyRequests:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много попыток входа, повторите позже"
        ) from None
    return LoginRequestOut(
        nonce=request.nonce,
        code=login.comparison_code(request.nonce),
        deeplink=f"{link}?start={login.DEEPLINK_PREFIX}{request.nonce}",
        expires_at=request.expires_at,
    )


@router.get("/auth/poll/{nonce}")
async def poll(nonce: str, db: Database, secret: JwtSecret) -> PollOut:
    telegram_id = await login.consume(db, nonce)
    if telegram_id is not None:
        user = ensure_allowed(await get_by_telegram_id(db, telegram_id))
        return PollOut(status="ok", tokens=issue_tokens(user, secret))
    if await login.find_active(db, nonce) is None:
        raise HTTPException(status.HTTP_410_GONE, "Запрос на вход устарел, начните заново")
    return PollOut(status="pending")


@router.post("/auth/refresh")
async def refresh(body: RefreshIn, db: Database, secret: JwtSecret) -> Tokens:
    try:
        user_id = security.read_token(body.refresh_token, "refresh", secret)
    except security.AuthError:
        raise unauthorized() from None
    user = await db.get(User, user_id)
    if not can_sign_in(user):
        raise unauthorized()
    return issue_tokens(user, secret)


@router.get("/me")
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
