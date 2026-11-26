import json

import httpx
import pytest

from app.core.config import get_config
from app.core.settings_store import parse_settings
from app.services.dadata import client as dadata_client
from app.services.dadata.client import DadataError, check_keys, parse_party, search
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


def party_response(request: httpx.Request):
    data = {"inn": "500100732259", "type": "INDIVIDUAL", "kpp": "x", "management": {"name": "x"}}
    return httpx.Response(200, json={"suggestions": [{"value": "ИП Тест", "data": data}]})


@pytest.mark.parametrize(
    ("query", "url", "branch"),
    [
        (" Ромашка  ", dadata_client.SUGGEST_URL, None),
        ("7707083893", dadata_client.FIND_URL, "MAIN"),
        ("500100732259", dadata_client.FIND_URL, "MAIN"),
    ],
)
async def test_dadata_search(query, url, branch):
    dadata_client.cache.clear()
    seen = []

    def handler(request):
        seen.append(request)
        return party_response(request)

    for _ in range(2):
        [party] = await search(query, "key", 5, dadata(handler))

    assert len(seen) == 1  # второй раз из кэша
    assert str(seen[0].url) == url
    assert json.loads(seen[0].content).get("branch_type") == branch
    assert (party.entity_type, party.kpp, party.director_name) == ("ip", "", "")
    assert party.region_code == "50"
    assert dadata_client.cached_party("500100732259") == party
    await search(query, "key", 5, dadata(handler), use_cache=False)
    assert len(seen) == 2


def test_dadata_skips_records_without_inn():
    assert parse_party({"value": "x", "data": {}}) is None


async def test_dadata_search_bad_answer():
    dadata_client.cache.clear()
    transport = dadata(lambda _: httpx.Response(200, json={"error": 1}))

    with pytest.raises(DadataError, match="непонятный"):
        await search("запрос", "key", 5, transport)
