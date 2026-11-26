from app.core.config import Config
from app.main import create_app


def make_config(monkeypatch, **env: str) -> Config:
    for name in ("APP_ENV", "ADMIN_TELEGRAM_ID", "BOT_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db/x")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return Config()


def test_app_env_defaults_to_prod(monkeypatch):
    assert make_config(monkeypatch).is_dev is False


def test_empty_values_are_treated_as_missing(monkeypatch):
    config = make_config(monkeypatch, ADMIN_TELEGRAM_ID="", BOT_TOKEN="")

    assert config.admin_telegram_id is None
    assert config.bot_token is None


def test_api_docs_only_in_dev(monkeypatch):
    assert create_app(make_config(monkeypatch, APP_ENV="dev")).docs_url == "/api/docs"

    prod = create_app(make_config(monkeypatch, APP_ENV="prod"))
    assert prod.docs_url is None
    assert prod.openapi_url is None
