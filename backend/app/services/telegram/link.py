from app.core.config import get_config
from app.core.settings_store import AppSettings
from app.services.telegram.status import read_status, status_path


def bot_username(settings: AppSettings) -> str | None:
    """Имя бота: у работающего бота, иначе из настроек."""
    status = read_status(status_path(get_config().settings_path))
    # Настоящее имя надёжнее введённого руками: ошибка в нём увела бы вход на чужого бота.
    username = status.get("username") or settings.telegram.bot_username.strip().lstrip("@")
    return username or None


def bot_link(settings: AppSettings) -> str | None:
    username = bot_username(settings)
    return f"https://t.me/{username}" if username else None
