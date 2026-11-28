"""Настройки приложения из settings.json.

Единственная точка доступа к файлу: валидация, атомарная запись под flock, бэкапы,
отслеживание изменений и маскирование секретов.
"""

import asyncio
import contextlib
import fcntl
import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.core.config import get_config

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
MASK = "••••"
BACKUPS_KEPT = 20
CHECK_INTERVAL_SECONDS = 2.0
WATCH_INTERVAL_SECONDS = 5.0
SECRET_PATHS = ("telegram.proxy.password", "dadata.api_key", "dadata.secret_key")

# Апгрейды схемы: UPGRADES[n] превращает данные версии n в версию n + 1.
UPGRADES: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


class Section(BaseModel):
    # Лишние поля запрещены, чтобы опечатка при ручной правке не прошла молча.
    model_config = ConfigDict(extra="forbid")


class CompanySettings(Section):
    name: str = "ООО «Ваша бухгалтерия»"
    support_contact: str = ""
    timezone: str = "Europe/Moscow"
    privacy_policy_url: str = ""
    # на кого выпускают электронные подписи: список для выбора в карточке компании
    signature_holders: list[str] = Field(
        default_factory=lambda: ["Генеральный директор", "Главный бухгалтер", "Менеджер"]
    )

    @field_validator("signature_holders")
    @classmethod
    def holders(cls, value: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(name for item in value if (name := " ".join(item.split()))))
        if len(cleaned) > 30 or any(len(name) > 100 for name in cleaned):
            raise ValueError("не больше 30 названий, каждое не длиннее 100 знаков")
        return cleaned

    @field_validator("privacy_policy_url")
    @classmethod
    def web_address(cls, value: str) -> str:
        if value and not value.startswith(("https://", "http://")):
            raise ValueError("ссылка должна начинаться с https://")
        return value

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("неизвестный часовой пояс") from error
        return value


class ProxySettings(Section):
    enabled: bool = False
    type: Literal["socks5"] = "socks5"
    host: str = ""
    port: int = Field(1080, ge=1, le=65535)
    username: str = ""
    password: str = ""
    rdns: bool = True

    @model_validator(mode="after")
    def host_required_when_enabled(self) -> "ProxySettings":
        if self.enabled and not self.host.strip():
            raise ValueError("прокси включён, но не указан host")
        if any(char in self.host for char in "/@ "):
            raise ValueError("host — только имя или IP, без схемы, логина и пробелов")
        return self


class TelegramSettings(Section):
    bot_username: str = ""
    mini_app_url: str = ""
    # кнопка входа Telegram на сайте; домен нужно указать боту в @BotFather (/setdomain)
    login_widget: bool = False
    proxy: ProxySettings = Field(default_factory=ProxySettings)


class DadataSettings(Section):
    enabled: bool = True
    api_key: str = ""
    secret_key: str = ""
    timeout_seconds: int = Field(10, ge=1, le=120)


class RosstatSettings(Section):
    # включают после загрузки корневого сертификата Минцифры
    enabled: bool = False
    # время ежедневного поиска форм по Москве
    search_time: str = Field("03:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timeout_seconds: int = Field(30, ge=5, le=120)


class NotificationSettings(Section):
    digest_time: str = Field("09:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    digest_workdays_only: bool = True
    default_client_offsets_days: list[int] = Field(default_factory=lambda: [7, 3, 1])
    remind_on_due_day: bool = True
    fill_amount_workdays_before: int = Field(5, ge=0, le=60)
    overdue_notify: bool = True
    signature_offsets_days: list[int] = Field(default_factory=lambda: [30, 14, 7, 1])
    # требования инспекции: за сколько рабочих дней напоминать; 0 — в сам день
    demand_receipt_offsets_days: list[int] = Field(default_factory=lambda: [2, 1, 0])
    demand_response_offsets_days: list[int] = Field(default_factory=lambda: [5, 3, 1, 0])
    # напоминать о требованиях и администратору с главным бухгалтером, а не только ответственному
    demand_notify_admin: bool = True
    # присылать помощникам напоминания о сроках по их компаниям
    assistant_reminders: bool = False
    # напоминать клиентам о сроке исполнения требования
    demand_notify_clients: bool = True
    # напоминать администратору, если «make backup» давно не создавал копию
    backup_alert: bool = True

    @field_validator("demand_receipt_offsets_days", "demand_response_offsets_days")
    @classmethod
    def demand_offsets(cls, value: list[int]) -> list[int]:
        if any(days < 0 or days > 60 for days in value):
            raise ValueError("дни напоминаний о требованиях должны быть от 0 до 60")
        return value

    @field_validator("default_client_offsets_days", "signature_offsets_days")
    @classmethod
    def positive_offsets(cls, value: list[int]) -> list[int]:
        if any(days < 1 or days > 365 for days in value):
            raise ValueError("дни напоминаний должны быть от 1 до 365")
        return value


class TaskSettings(Section):
    generation_horizon_months_ahead: int = Field(15, ge=1, le=36)
    client_can_unmark_own_paid_hours: int = Field(24, ge=0, le=720)
    show_notices_to_clients: bool = True


class AppSettings(Section):
    version: int = SCHEMA_VERSION
    company: CompanySettings = Field(default_factory=CompanySettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    dadata: DadataSettings = Field(default_factory=DadataSettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    tasks: TaskSettings = Field(default_factory=TaskSettings)
    rosstat: RosstatSettings = Field(default_factory=RosstatSettings)


class SettingsError(Exception):
    """Настройки не прошли проверку. Текст не содержит значений, только пути и причины."""


def parse_settings(data: Any) -> AppSettings:
    if not isinstance(data, dict):
        raise SettingsError("в корне должен быть JSON-объект")
    version = data.get("version", SCHEMA_VERSION)
    if not isinstance(version, int) or not 1 <= version <= SCHEMA_VERSION:
        raise SettingsError(f"version: поддерживаются версии 1–{SCHEMA_VERSION}")
    while version < SCHEMA_VERSION:
        data = UPGRADES[version](data)
        version += 1
        data["version"] = version
    try:
        return AppSettings.model_validate(data)
    except ValidationError as error:
        # str(error) содержит введённые значения, в том числе секреты, поэтому не используется.
        problems = "; ".join(
            f"{'.'.join(map(str, item['loc'])) or 'файл'}: {item['msg']}"
            for item in error.errors(include_input=False, include_url=False)
        )
        raise SettingsError(problems) from None


def parse_settings_text(raw: bytes) -> AppSettings:
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise SettingsError("файл не в кодировке UTF-8") from None
    except json.JSONDecodeError as error:
        raise SettingsError(
            f"синтаксическая ошибка JSON, строка {error.lineno}, столбец {error.colno}: {error.msg}"
        ) from None
    return parse_settings(data)


def masked_settings(settings: AppSettings) -> dict[str, Any]:
    """Представление для API: вместо секретов — маска и признак has_*."""
    data = settings.model_dump()
    for path in SECRET_PATHS:
        section, key = _locate(data, path)
        section[f"has_{key}"] = bool(section[key])
        section[key] = MASK if section[key] else ""
    return data


def _locate(data: dict[str, Any], path: str) -> tuple[dict[str, Any], str]:
    *sections, key = path.split(".")
    for name in sections:
        data = data[name]
    return data, key


def _merge(base: dict[str, Any], patch: dict[str, Any], prefix: str = "") -> list[str]:
    """Накладывает patch на base и возвращает пути изменённых полей."""
    changed: list[str] = []
    for key, value in patch.items():
        path = f"{prefix}{key}"
        if key.startswith("has_") and f"{prefix}{key[4:]}" in SECRET_PATHS:
            continue
        if path in SECRET_PATHS and value in ("", None, MASK):
            continue  # пустое поле = не менять
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            changed += _merge(base[key], value, f"{path}.")
        elif key not in base or base[key] != value:
            base[key] = value
            changed.append(path)
    return changed


def _diff(old: dict[str, Any], new: dict[str, Any], prefix: str, changed: list[str]) -> None:
    """Пути полей, которыми new отличается от old."""
    for key, value in new.items():
        if isinstance(value, dict):
            _diff(old[key], value, f"{prefix}{key}.", changed)
        elif old[key] != value:
            changed.append(f"{prefix}{key}")


Listener = Callable[[AppSettings], None]
ErrorListener = Callable[[str], None]


class SettingsStore:
    def __init__(
        self,
        path: str | Path,
        check_interval: float = CHECK_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.path = Path(path)
        self.backups_dir = self.path.parent / "backups"
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self._check_interval = check_interval
        self._clock = clock
        self._lock = threading.RLock()
        self._current: AppSettings | None = None
        self._signature: tuple[int, int, int] | None = None
        self._checked_at = 0.0
        self._error: str | None = None
        self._listeners: list[Listener] = []
        self._error_listeners: list[ErrorListener] = []

    @property
    def last_error(self) -> str | None:
        """Причина, по которой файл на диске сейчас не используется."""
        return self._error

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        """Вызывает listener при каждом изменении настроек. Возвращает функцию отписки."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def subscribe_errors(self, listener: ErrorListener) -> Callable[[], None]:
        self._error_listeners.append(listener)
        return lambda: self._error_listeners.remove(listener)

    def get(self) -> AppSettings:
        with self._lock:
            if self._current is None or self._clock() - self._checked_at >= self._check_interval:
                self.reload()
            return self._current.model_copy(deep=True)

    def reload(self) -> None:
        """Перечитывает файл, если он изменился."""
        with self._lock:
            self._checked_at = self._clock()
            try:
                stat = self.path.stat()
                signature = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
                if signature == self._signature and self._current is not None:
                    return
                self._signature = signature
                settings = parse_settings_text(self.path.read_bytes())
            except FileNotFoundError:
                self._signature = None
                if self._current is None:
                    self._current = AppSettings()
                return
            except (OSError, SettingsError) as error:
                self._fail(str(error) if isinstance(error, SettingsError) else type(error).__name__)
                return
            self._error = None
            self._apply(settings)

    def _fail(self, reason: str) -> None:
        if self._current is None:
            self._current = self._latest_valid_backup() or AppSettings()
        if reason == self._error:
            return
        self._error = reason
        logger.error(
            "Файл настроек %s не применён, работаем на последней рабочей версии. %s",
            self.path,
            reason,
        )
        for listener in list(self._error_listeners):
            self._notify(listener, reason)

    def _apply(self, settings: AppSettings) -> None:
        previous, self._current = self._current, settings
        if previous is not None and previous != settings:
            logger.info("Настройки обновлены")
            for listener in list(self._listeners):
                self._notify(listener, settings.model_copy(deep=True))

    @staticmethod
    def _notify(listener: Callable[[Any], None], value: Any) -> None:
        try:
            listener(value)
        except Exception:
            logger.exception("Ошибка в подписчике настроек")

    def list_backups(self) -> list[Path]:
        """Бэкапы от новых к старым."""
        return sorted(self.backups_dir.glob("settings-*.json"), reverse=True)

    def _latest_valid_backup(self) -> AppSettings | None:
        for backup in self.list_backups():
            try:
                settings = parse_settings_text(backup.read_bytes())
            except (OSError, SettingsError):
                continue
            logger.warning("Настройки взяты из резервной копии %s", backup.name)
            return settings
        return None

    def ensure_file(self) -> None:
        """Создаёт файл с настройками по умолчанию, если его нет."""
        with self._lock, self._file_lock():
            if not self.path.exists():
                self._write(AppSettings())
                logger.info("Создан файл настроек %s", self.path)
        self.reload()

    def update(
        self,
        patch: dict[str, Any],
        user: object = None,
        clear: Iterable[str] = (),
    ) -> AppSettings:
        """Частично обновляет настройки.

        Пустое значение или маска в секретном поле означают «не менять»;
        чтобы удалить секрет, передайте его путь в clear.
        """
        return self.update_with_changes(patch, user, clear)[0]

    def update_with_changes(
        self,
        patch: dict[str, Any],
        user: object = None,
        clear: Iterable[str] = (),
    ) -> tuple[AppSettings, list[str]]:
        """То же, что update, и пути изменённых полей (без значений)."""
        clear = tuple(clear)
        if unknown := set(clear) - set(SECRET_PATHS):
            raise SettingsError(f"очищать можно только секретные поля, не: {sorted(unknown)}")
        with self._lock, self._file_lock():
            self._reload_forced()  # свежая версия с диска: её мог изменить другой процесс
            data = self._current.model_dump()
            changed = _merge(data, {k: v for k, v in patch.items() if k != "version"})
            for path in clear:
                section, key = _locate(data, path)
                if section[key]:
                    section[key] = ""
                    changed.append(path)
            settings = parse_settings(data)
            if changed:
                self._save(settings)
                # Только имена полей: значения могут быть секретами.
                logger.info(
                    "Пользователь %s изменил настройки: %s", user, ", ".join(sorted(changed))
                )
        return settings.model_copy(deep=True), sorted(changed)

    def restore(self, name: str, user: object = None) -> tuple[AppSettings, list[str]]:
        """Возвращает настройки из резервной копии. Текущая версия тоже сохраняется в копию."""
        with self._lock, self._file_lock():
            # Имя сверяется со списком: путь из запроса не используется.
            backup = next((path for path in self.list_backups() if path.name == name), None)
            if backup is None:
                raise FileNotFoundError(name)
            settings = parse_settings_text(backup.read_bytes())
            self._reload_forced()
            changed: list[str] = []
            _diff(self._current.model_dump(), settings.model_dump(), "", changed)
            if changed or self._error:
                self._save(settings)
                logger.info("Пользователь %s восстановил настройки из %s", user, name)
        return settings.model_copy(deep=True), sorted(changed)

    def _reload_forced(self) -> None:
        self._signature = None
        self.reload()

    def _save(self, settings: AppSettings) -> None:
        self._backup()
        self._write(settings)
        stat = self.path.stat()
        self._signature = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
        self._error = None
        self._apply(settings)

    @contextlib.contextmanager
    def _file_lock(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)  # закрытие снимает блокировку

    def _backup(self) -> None:
        try:
            previous = self.path.read_bytes()
        except FileNotFoundError:
            return
        self.backups_dir.mkdir(mode=0o700, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        atomic_write(self.backups_dir / f"settings-{stamp}.json", previous)
        for old in self.list_backups()[BACKUPS_KEPT:]:
            old.unlink(missing_ok=True)

    def _write(self, settings: AppSettings) -> None:
        text = json.dumps(settings.model_dump(), ensure_ascii=False, indent=2) + "\n"
        atomic_write(self.path, text.encode("utf-8"))

    async def watch(self, interval: float = WATCH_INTERVAL_SECONDS) -> None:
        """Следит за файлом, пока задачу не отменят."""
        while True:
            self.reload()
            await asyncio.sleep(interval)


def atomic_write(path: Path, content: bytes) -> None:
    """Временный файл → fsync → os.replace. Права 600."""
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(descriptor, "wb") as file:
            os.fchmod(file.fileno(), 0o600)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


@lru_cache
def get_store() -> SettingsStore:
    return SettingsStore(get_config().settings_path)


def get_settings() -> AppSettings:
    return get_store().get()


def update_settings(
    patch: dict[str, Any], user: object = None, clear: Iterable[str] = ()
) -> AppSettings:
    return get_store().update(patch, user, clear)
