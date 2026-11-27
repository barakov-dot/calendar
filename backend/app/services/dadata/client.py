"""Клиент DaData. Запросы идут напрямую: прокси для Telegram здесь не используется."""

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

SUGGEST_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/party"
FIND_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
BALANCE_URL = "https://dadata.ru/api/v2/profile/balance"
# ПАО Сбербанк: заведомо существующая организация для проверки ключей
CHECK_INN = "7707083893"

SUGGESTIONS_LIMIT = 10
CACHE_TTL_SECONDS = 3600
CACHE_SIZE = 500


class DadataError(Exception):
    """Текст показывается пользователю и не содержит ключей."""


@dataclass(frozen=True)
class Party:
    """Организация или ИП в терминах нашей карточки компании."""

    inn: str
    kpp: str
    ogrn: str
    name: str
    short_name: str
    address: str
    okved: str
    director_name: str
    entity_type: str  # ooo | ip
    region_code: str
    status: str  # ACTIVE, LIQUIDATING, LIQUIDATED, BANKRUPT, REORGANIZING
    raw: dict[str, Any] = field(repr=False, compare=False)
    registration_date: date | None = None  # только у ИП


def _text(value: Any, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _moscow_date(milliseconds: Any) -> date | None:
    """Дата из отметки времени DaData."""
    if not isinstance(milliseconds, int):
        return None
    try:
        return datetime.fromtimestamp(milliseconds / 1000, ZoneInfo("Europe/Moscow")).date()
    except (OverflowError, OSError, ValueError):
        return None


def parse_party(suggestion: dict[str, Any]) -> Party | None:
    data = suggestion.get("data") or {}
    inn = _text(data.get("inn"), 12)
    if len(inn) not in (10, 12) or not inn.isdigit():
        return None
    is_ip = data.get("type") == "INDIVIDUAL"
    names = data.get("name") or {}
    address = data.get("address") or {}
    kladr = _text((address.get("data") or {}).get("region_kladr_id"), 13)
    return Party(
        inn=inn,
        kpp="" if is_ip else _text(data.get("kpp"), 9),
        ogrn=_text(data.get("ogrn"), 15),
        name=_text(names.get("full_with_opf") or suggestion.get("value"), 1000),
        short_name=_text(names.get("short_with_opf") or suggestion.get("value"), 500),
        address=_text(address.get("unrestricted_value") or address.get("value"), 1000),
        okved=_text(data.get("okved"), 16),
        director_name="" if is_ip else _text((data.get("management") or {}).get("name"), 500),
        entity_type="ip" if is_ip else "ooo",
        region_code=(kladr or inn)[:2],
        status=_text((data.get("state") or {}).get("status"), 32),
        raw=suggestion,
        registration_date=_moscow_date((data.get("state") or {}).get("registration_date"))
        if is_ip
        else None,
    )


class _Cache:
    """Кэш в памяти процесса: подсказки не расходуют лимит запросов повторно."""

    def __init__(self) -> None:
        self._items: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Any:
        item = self._items.get(key)
        if item is None or time.monotonic() - item[0] > CACHE_TTL_SECONDS:
            return None
        return item[1]

    def put(self, key: str, value: Any) -> None:
        self._items[key] = (time.monotonic(), value)
        self._items.move_to_end(key)
        while len(self._items) > CACHE_SIZE:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()


cache = _Cache()


async def _request(client: httpx.AsyncClient, method: str, url: str, denied: str, **kwargs):
    try:
        response = await client.request(method, url, **kwargs)
    except httpx.TimeoutException:
        raise DadataError("DaData не ответила вовремя") from None
    except httpx.HTTPError:
        raise DadataError("Не удалось соединиться с DaData") from None
    if response.status_code in (401, 403):
        raise DadataError(denied)
    if response.status_code == 429:
        raise DadataError("DaData: слишком много запросов, повторите позже")
    if response.is_error:
        raise DadataError(f"DaData вернула ошибку {response.status_code}")
    try:
        return response.json()
    except ValueError:
        raise DadataError("DaData вернула непонятный ответ") from None


def _client(
    api_key: str, secret_key: str, timeout_seconds: int, transport: httpx.AsyncBaseTransport | None
) -> httpx.AsyncClient:
    if not api_key:
        raise DadataError("Не указан API-ключ")
    if not (api_key + secret_key).isascii():
        raise DadataError("В ключах есть недопустимые символы: скопируйте их заново")
    return httpx.AsyncClient(
        timeout=timeout_seconds,
        transport=transport,
        trust_env=False,
        headers={"Authorization": f"Token {api_key}", "Accept": "application/json"},
    )


DENIED = "DaData отклонила API-ключ или исчерпан лимит запросов"


async def search(
    query: str,
    api_key: str,
    timeout_seconds: int,
    transport: httpx.AsyncBaseTransport | None = None,
    use_cache: bool = True,
) -> list[Party]:
    """Подсказки по названию или поиск по ИНН/ОГРН (для организаций — головной офис)."""
    query = " ".join(query.split())
    by_id = query.isdigit() and len(query) in (10, 12, 13, 15)
    key = f"{'id' if by_id else 'q'}:{query.lower()}"
    if use_cache and (found := cache.get(key)) is not None:
        return found
    body: dict[str, Any] = {"query": query, "count": SUGGESTIONS_LIMIT}
    if by_id:
        body["branch_type"] = "MAIN"
    async with _client(api_key, "", timeout_seconds, transport) as client:
        data = await _request(client, "POST", FIND_URL if by_id else SUGGEST_URL, DENIED, json=body)
    try:
        parsed = [parse_party(item) for item in data["suggestions"]]
    except (KeyError, TypeError, AttributeError):
        raise DadataError("DaData вернула непонятный ответ") from None
    parties = [party for party in parsed if party is not None]
    cache.put(key, parties)
    for party in parties:
        cache.put(f"party:{party.inn}", party)
    return parties


def cached_party(inn: str) -> Party | None:
    """Организация, уже полученная из DaData этим процессом."""
    return cache.get(f"party:{inn}")


async def check_keys(
    api_key: str,
    secret_key: str,
    timeout_seconds: int,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """Тестовый поиск по ИНН и, если задан секретный ключ, проверка баланса."""
    async with _client(api_key, secret_key, timeout_seconds, transport) as client:
        found = await _request(client, "POST", FIND_URL, DENIED, json={"query": CHECK_INN})
        try:
            name = found["suggestions"][0]["value"]
        except (KeyError, IndexError, TypeError):
            raise DadataError("DaData не нашла тестовую организацию") from None
        if secret_key:
            await _request(
                client,
                "GET",
                BALANCE_URL,
                "DaData отклонила секретный ключ",
                headers={"X-Secret": secret_key},
            )
    checked = "оба ключа работают" if secret_key else "API-ключ работает (секретный не задан)"
    return f"{checked.capitalize()}, найдена организация «{name}»"
