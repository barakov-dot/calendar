import pytest
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiohttp_socks import ProxyConnector, ProxyError

from app.core.config import Config
from app.core.settings_store import AppSettings, parse_settings
from app.services.telegram.factory import (
    ProxyConfigError,
    build_session,
    create_bot,
    resolve_proxy,
)
from tests.fakes import PROXIED_HOST, TOKEN, FakeSocks5, FakeTelegram

ENV_URL = "socks5://env-user:env-pass@env.example:1081"


def with_proxy(**proxy) -> AppSettings:
    return parse_settings(
        {"telegram": {"proxy": {"enabled": True, "host": "json.example"} | proxy}}
    )


def test_settings_proxy_has_priority_over_env():
    proxy = resolve_proxy(with_proxy(port=1090), ENV_URL)

    assert (proxy.url, proxy.source) == ("socks5://json.example:1090", "settings.json")


def test_env_proxy_used_when_disabled_in_settings():
    settings = parse_settings({"telegram": {"proxy": {"enabled": False, "host": "json.example"}}})

    proxy = resolve_proxy(settings, ENV_URL)

    assert (proxy.url, proxy.source, proxy.rdns) == (ENV_URL, ".env", True)


@pytest.mark.parametrize("env_url", [None, "", "   "])
def test_direct_connection_without_proxy(env_url):
    assert resolve_proxy(AppSettings(), env_url) is None
    session = build_session(AppSettings(), env_url)
    assert session.proxy is None
    assert session._connector_type is not ProxyConnector


@pytest.mark.parametrize("rdns", [True, False])
def test_session_with_socks5(rdns):
    session = build_session(with_proxy(username="u@x", password="p:/#@ ы", rdns=rdns))

    assert isinstance(session, AiohttpSession)
    assert session._connector_type is ProxyConnector
    init = session._connector_init
    assert (init["host"], init["port"], init["rdns"]) == ("json.example", 1080, rdns)
    # спецсимволы переживают упаковку в URL
    assert (init["username"], init["password"]) == ("u@x", "p:/#@ ы")


def test_socks5h_is_accepted_in_env():
    assert resolve_proxy(AppSettings(), "socks5h://host.example:1080").url.startswith("socks5://")


@pytest.mark.parametrize(
    "url",
    ["http://u:secret@host:1", "u:secret@host:1", "socks5://u:secret@host", "socks5://h:port"],
)
def test_bad_env_proxy_is_an_error_not_direct_connection(url):
    with pytest.raises(ProxyConfigError) as error:
        resolve_proxy(AppSettings(), url)

    assert "secret" not in str(error.value)


def test_password_not_visible_in_text_of_proxy():
    proxy = resolve_proxy(with_proxy(username="login", password="secret"), None)

    assert "secret" not in f"{proxy} {proxy!r}"
    assert "login" not in f"{proxy} {proxy!r}"
    assert "json.example:1080" in str(proxy)


def make_config(monkeypatch) -> Config:
    monkeypatch.setenv("BOT_TOKEN", TOKEN)
    return Config()


def local_proxy(port: int, **extra) -> AppSettings:
    return with_proxy(host="127.0.0.1", port=port, **extra)


async def test_request_goes_through_socks5_with_auth_and_remote_dns(monkeypatch):
    async with FakeTelegram() as telegram, FakeSocks5(username="u", password="p") as socks:
        settings = local_proxy(socks.port, username="u", password="p")
        bot = create_bot(make_config(monkeypatch), resolve_proxy(settings, None), telegram.api())
        try:
            me = await bot.get_me()
        finally:
            await bot.session.close()

    assert me.username == "test_bot"
    assert socks.targets == [PROXIED_HOST]  # имя разрешал прокси


async def test_wrong_proxy_password_fails_without_direct_fallback(monkeypatch):
    async with FakeTelegram() as telegram, FakeSocks5(username="u", password="p") as socks:
        settings = local_proxy(socks.port, username="u", password="wrong")
        bot = create_bot(
            make_config(monkeypatch), resolve_proxy(settings, None), telegram.api("127.0.0.1")
        )
        try:
            with pytest.raises((TelegramNetworkError, ProxyError)):
                await bot.get_me()
        finally:
            await bot.session.close()

    assert socks.rejected == 1
    assert telegram.calls == []
