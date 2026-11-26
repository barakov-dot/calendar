"""Проверка здоровья контейнеров bot и worker: python -m app.healthcheck bot|worker.

Здоров, пока процесс обновляет свой файл статуса.
"""

import sys
import time

from app.core.config import get_config
from app.services.monitoring import read_worker, worker_status_path
from app.services.telegram.status import read_status, status_path


def healthy(service: str, now: float) -> bool:
    settings_path = get_config().settings_path
    if service == "bot":
        # недоступность Telegram — не повод считать процесс сломанным
        return read_status(status_path(settings_path), now)["state"] not in ("unknown", "stopped")
    if service == "worker":
        return read_worker(worker_status_path(settings_path), now) is not None
    raise ValueError(service)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("bot", "worker"):
        sys.exit("Использование: python -m app.healthcheck bot|worker")
    sys.exit(0 if healthy(sys.argv[1], time.time()) else 1)
