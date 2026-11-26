"""Инфраструктурные настройки из окружения (.env). Остальное — в settings.json."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_ignore_empty=True, extra="ignore")

    database_url: SecretStr
    # По умолчанию prod: забытая переменная не должна включить dev-возможности.
    app_env: Literal["dev", "prod"] = "prod"
    app_domain: str = ""
    settings_path: str = "/app/config/settings.json"
    bot_token: SecretStr | None = None
    jwt_secret: SecretStr | None = None
    admin_telegram_id: int | None = None
    telegram_proxy_url: SecretStr | None = None

    @property
    def is_dev(self) -> bool:
        return self.app_env == "dev"


@lru_cache
def get_config() -> Config:
    return Config()
