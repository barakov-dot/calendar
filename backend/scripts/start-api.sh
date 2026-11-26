#!/bin/sh
# Применяет миграции и запускает API. Аргументы передаются в uvicorn.
set -e
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 "$@"
