"""Планировщик рассылок: python -m app.worker. Задания появятся в Фазе 6."""

from app.core.service import run_service

if __name__ == "__main__":
    run_service("worker")
