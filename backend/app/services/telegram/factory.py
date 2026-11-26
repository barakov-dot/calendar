"""Единственное место, где создаются Bot и HTTP-сессия для Telegram.

Приоритет прокси: settings.json (если включён) → TELEGRAM_PROXY_URL из .env → напрямую.
"""

from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import quote, urlsplit

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import PRODUCTION, TelegramAPIServer
from pydantic import SecretStr

from app.core.config import Config
from app.core.settings_store import AppSettings


class ProxyConfigError(ValueError):
    """Прокси задан неверно. Текст не содержит логин и пароль."""


@dataclass(frozen=True)
class Proxy:
    url: str = field(repr=False)  # содержит пароль
    rdns: bool
    source: Literal["settings.json", ".env"]

    def __str__(self) -> str:
        parts = urlsplit(self.url)
        return f"{parts.scheme}://{parts.hostname}:{parts.port} (из {self.source})"


def resolve_proxy(settings: AppSettings, env_proxy_url: SecretStr | str | None) -> Proxy | None:
    configured = settings.telegram.proxy
    if configured.enabled:
        auth = ""
        if configured.username or configured.password:
            auth = f"{quote(configured.username, safe='')}:{quote(configured.password, safe='')}@"
        host = configured.host.strip()
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"  # IPv6
        url = f"socks5://{auth}{host}:{configured.port}"
        return Proxy(url=url, rdns=configured.rdns, source="settings.json")

    if isinstance(env_proxy_url, SecretStr):
        env_proxy_url = env_proxy_url.get_secret_value()
    if not env_proxy_url or not env_proxy_url.strip():
        return None
    return _proxy_from_env(env_proxy_url.strip())


def _proxy_from_env(url: str) -> Proxy:
    # Ошибка в прокси не должна приводить к тихой отправке напрямую.
    example = "ожидается socks5://user:password@host:port"
    try:
        parts = urlsplit(url)
        valid = parts.scheme in ("socks5", "socks5h") and parts.hostname and parts.port
    except ValueError:
        valid = False
    if not valid:
        raise ProxyConfigError(f"TELEGRAM_PROXY_URL задан неверно: {example}")
    return Proxy(url=f"socks5://{url.split('://', 1)[1]}", rdns=True, source=".env")


def session_for_proxy(proxy: Proxy | None, **kwargs) -> AiohttpSession:
    if proxy is None:
        return AiohttpSession(**kwargs)
    session = AiohttpSession(proxy=proxy.url, **kwargs)
    # aiogram всегда включает rdns и не даёт параметра; поведение закреплено тестом.
    session._connector_init["rdns"] = proxy.rdns
    return session


def build_session(
    settings: AppSettings, env_proxy_url: SecretStr | str | None = None, **kwargs
) -> AiohttpSession:
    return session_for_proxy(resolve_proxy(settings, env_proxy_url), **kwargs)


def create_bot(config: Config, proxy: Proxy | None, api: TelegramAPIServer = PRODUCTION) -> Bot:
    if config.bot_token is None:
        raise ValueError("BOT_TOKEN не задан")
    return Bot(
        token=config.bot_token.get_secret_value(),
        session=session_for_proxy(proxy, api=api),
    )
