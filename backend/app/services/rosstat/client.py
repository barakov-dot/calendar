"""Запросы к websbor. Идут напрямую (прокси для Telegram не используется).

Сайт подписан Национальным удостоверяющим центром Минцифры. Его корневой сертификат
администратор загружает в настройках; он действует только для этих запросов. Проверка
сертификата не отключается.
"""

import ssl
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_config

BASE_URL = "https://websbor.rosstat.gov.ru/webstat/api/gs"
# коды записей статрегистра: 1 — организация, 4 — ИП; остальные — подразделения
HEAD_TYPES = (1, 4)
CERTIFICATE_MAX_BYTES = 100 * 1024


class RosstatError(Exception):
    """Текст показывается пользователю."""


class Unavailable(RosstatError):
    """Нет связи с сервисом: остальные организации проверять сейчас бессмысленно."""


def certificate_path() -> Path:
    return Path(get_config().settings_path).parent / "rosstat-ca.cer"


def _context(certificate: bytes | None) -> ssl.SSLContext:
    context = ssl.create_default_context()
    if certificate:
        # PEM — текстом, DER (обычный .cer) — байтами
        data: str | bytes = certificate
        if b"-----BEGIN" in certificate:
            data = certificate.decode("ascii", errors="ignore")
        context.load_verify_locations(cadata=data)
    return context


def save_certificate(data: bytes) -> None:
    if not data or len(data) > CERTIFICATE_MAX_BYTES:
        raise RosstatError("Это не похоже на файл сертификата")
    try:
        _context(data)
    except (ssl.SSLError, ValueError):
        raise RosstatError("Файл не читается как сертификат (.cer, .crt или .pem)") from None
    path = certificate_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _certificate() -> bytes | None:
    path = certificate_path()
    return path.read_bytes() if path.is_file() else None


def _is_certificate_error(error: BaseException | None) -> bool:
    while error is not None:
        if isinstance(error, ssl.SSLCertVerificationError):
            return True
        error = error.__cause__ or error.__context__
    return False


class Client:
    def __init__(self, timeout: int, transport: httpx.AsyncBaseTransport | None = None) -> None:
        try:
            context = _context(_certificate())
        except (OSError, ssl.SSLError, ValueError):
            raise Unavailable("Файл сертификата повреждён: загрузите его заново") from None
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=timeout,
            transport=transport,
            verify=context,
            trust_env=False,
            headers={"Accept": "application/json"},
        )

    async def __aenter__(self) -> "Client":
        return self

    async def __aexit__(self, *_) -> None:
        await self._http.aclose()

    async def _request(self, method: str, url: str, **kwargs) -> Any:
        try:
            response = await self._http.request(method, url, **kwargs)
        except httpx.TimeoutException:
            raise Unavailable("Росстат не ответил вовремя") from None
        except httpx.HTTPError as error:
            if _is_certificate_error(error):
                raise Unavailable(
                    "Не проверен сертификат сайта Росстата: загрузите корневой сертификат "
                    "Минцифры в настройках"
                ) from None
            raise Unavailable("Нет соединения с сайтом Росстата") from None
        if response.status_code >= 500 or response.status_code == 429:
            raise Unavailable(f"Росстат временно не отвечает (ошибка {response.status_code})")
        if response.is_error:
            raise RosstatError(f"Росстат вернул ошибку {response.status_code}")
        try:
            return response.json()
        except ValueError:
            raise RosstatError("Росстат вернул непонятный ответ") from None

    async def organization(self, inn: str) -> dict[str, Any] | None:
        """Головная запись статрегистра по ИНН."""
        found = await self._request(
            "POST", "/organizations", json={"okpo": "", "inn": inn, "ogrn": ""}
        )
        if not isinstance(found, list):
            raise RosstatError("Росстат вернул непонятный ответ")
        same = [
            item
            for item in found
            if isinstance(item, dict) and str(item.get("inn", "")).strip() == inn and item.get("id")
        ]
        heads = [item for item in same if item.get("type") in HEAD_TYPES]
        return next(iter(heads or same), None)

    async def forms(self, organization_id: object) -> list[dict[str, Any]]:
        found = await self._request("GET", f"/organizations/{organization_id}/forms")
        if not isinstance(found, list) or not all(isinstance(item, dict) for item in found):
            raise RosstatError("Росстат вернул непонятный ответ")
        return found
