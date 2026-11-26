"""Клиент DaData. Запросы идут напрямую: прокси для Telegram здесь не используется."""

import httpx

SUGGEST_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
BALANCE_URL = "https://dadata.ru/api/v2/profile/balance"
# ПАО Сбербанк: заведомо существующая организация для проверки ключей
CHECK_INN = "7707083893"


class DadataError(Exception):
    """Текст показывается пользователю и не содержит ключей."""


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


async def check_keys(
    api_key: str,
    secret_key: str,
    timeout_seconds: int,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """Тестовый поиск по ИНН и, если задан секретный ключ, проверка баланса."""
    if not api_key:
        raise DadataError("Не указан API-ключ")
    if not (api_key + secret_key).isascii():
        raise DadataError("В ключах есть недопустимые символы: скопируйте их заново")
    async with httpx.AsyncClient(
        timeout=timeout_seconds,
        transport=transport,
        trust_env=False,
        headers={"Authorization": f"Token {api_key}", "Accept": "application/json"},
    ) as client:
        found = await _request(
            client,
            "POST",
            SUGGEST_URL,
            "DaData отклонила API-ключ или исчерпан лимит запросов",
            json={"query": CHECK_INN},
        )
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
