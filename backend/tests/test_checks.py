import httpx
import pytest

from app.core.config import get_config
from app.core.settings_store import parse_settings
from app.services.dadata.client import DadataError, check_keys
from app.services.telegram import check
from app.services.telegram.factory import resolve_proxy
from app.services.telegram.status import BotStatus, read_status
from tests.fakes import FakeSocks5, FakeTelegram

pytestmark = pytest.mark.usefixtures("secrets")


def proxy(port: int, password: str = "p"):
    data = {"enabled": True, "host": "127.0.0.1", "port": port, "username": "u"}
    return resolve_proxy(parse_settings({"telegram": {"proxy": data | {"password": password}}}), "")


async def test_check_success():
    async with FakeTelegram() as telegram, FakeSocks5("u", "p") as socks:
        result = await check.check_connection(get_config(), proxy(socks.port), telegram.api())

    assert result.ok
    assert "Бот @test_bot доступен, задержка" in result.message


async def test_check_proxy_down():
    async with FakeSocks5() as dead:
        port = dead.port

    result = await check.check_connection(get_config(), proxy(port))

    assert (result.ok, result.message) == (False, check.NO_PROXY_CONNECTION)


async def test_check_wrong_password():
    async with FakeTelegram() as telegram, FakeSocks5("u", "p") as socks:
        result = await check.check_connection(
            get_config(), proxy(socks.port, "wrong"), telegram.api()
        )

    assert (result.ok, result.message) == (False, check.BAD_CREDENTIALS)


async def test_check_telegram_unreachable_through_proxy():
    async with FakeTelegram() as gone:
        api = gone.api()  # после выхода из блока порт закрыт
    async with FakeSocks5("u", "p") as socks:
        result = await check.check_connection(get_config(), proxy(socks.port), api, 2)

    assert (result.ok, result.message) == (False, check.TELEGRAM_BEHIND_PROXY)


async def test_check_without_token(monkeypatch):
    monkeypatch.delenv("BOT_TOKEN")
    get_config.cache_clear()

    result = await check.check_connection(get_config(), None)

    assert "BOT_TOKEN не задан" in result.message


def dadata(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


async def test_dadata_checks_both_keys():
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(200, json={"suggestions": [{"value": "ПАО СБЕРБАНК"}]})

    message = await check_keys("key", "secret", 5, dadata(handler))

    assert "ПАО СБЕРБАНК" in message
    assert seen[0].headers["authorization"] == "Token key"
    assert "x-secret" not in seen[0].headers
    assert seen[1].headers["x-secret"] == "secret"


@pytest.mark.parametrize(
    ("api_key", "response", "message"),
    [
        ("", httpx.Response(200), "Не указан API-ключ"),
        ("ключ", httpx.Response(200), "недопустимые символы"),
        ("key", httpx.Response(403), "отклонила API-ключ"),
        ("key", httpx.Response(500), "ошибку 500"),
        ("key", httpx.Response(200, text="<html>"), "непонятный ответ"),
        ("key", httpx.Response(200, json={"suggestions": []}), "не нашла"),
    ],
)
async def test_dadata_errors(api_key, response, message):
    with pytest.raises(DadataError, match=message):
        await check_keys(api_key, "", 5, dadata(lambda _: response))


async def test_dadata_network_error():
    def handler(request):
        raise httpx.ConnectError("нет сети")

    with pytest.raises(DadataError, match="соединиться"):
        await check_keys("key", "", 5, dadata(handler))


def test_bot_status_states(tmp_path):
    now = [1000.0]
    status = BotStatus(tmp_path / "bot_status.json", clock=lambda: now[0])

    def state(later: float = 0) -> str:
        status.save()
        return read_status(status.path, now[0] + later)["state"]

    assert state() == "connecting"
    status.success()
    assert state() == "connected"
    assert state(later=61) == "stopped"
    now[0] += 91
    assert state() == "error"  # давно нет ответа
    status.success()
    status.failure("socks5://u:pa55@host refused")
    assert state() == "error"
    now[0] += 300
    status.failure("ещё раз")
    assert state() == "unavailable"
    status.failure("socks5://u:pa55@host refused")
    status.save()
    assert "pa55" not in status.path.read_text()
    status.blocked("BOT_TOKEN не задан")
    assert state() == "problem"
