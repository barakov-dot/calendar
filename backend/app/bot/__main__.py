"""Telegram-бот: python -m app.bot. Long polling появится в Фазе 1."""

from app.core.service import run_service

if __name__ == "__main__":
    run_service("bot")
