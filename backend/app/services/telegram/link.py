from app.core.config import get_config
from app.core.settings_store import AppSettings
from app.services.telegram.status import read_status, status_path


def bot_link(settings: AppSettings) -> str | None:
    """https://t.me/<имя бота>. Имя берётся у работающего бота, иначе из настроек."""
    status = read_status(status_path(get_config().settings_path))
    # Настоящее имя надёжнее введённого руками: ошибка в нём увела бы вход на чужого бота.
    username = status.get("username") or settings.telegram.bot_username.strip().lstrip("@")
    return f"https://t.me/{username}" if username else None
