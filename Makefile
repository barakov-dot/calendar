COMPOSE := docker compose -f docker-compose.yml
DEV := $(COMPOSE) -f docker-compose.dev.yml
PROD := $(COMPOSE) -f docker-compose.prod.yml

.DEFAULT_GOAL := help
.PHONY: help env dev down migrate test lint logs prod

help: ## Список команд
	@grep -hE '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

env:
	@test -f .env || { echo "Нет файла .env. Создайте его: cp .env.example .env"; exit 1; }

dev: env ## Запустить всё для разработки
	$(DEV) up --build

down: env ## Остановить контейнеры (данные базы сохраняются)
	$(DEV) down

migrate: env ## alembic upgrade head в контейнере api
	$(DEV) exec api alembic upgrade head

test: env ## pytest в контейнере api
	$(DEV) build api
	$(DEV) run --rm api pytest

lint: env ## ruff + eslint (и проверка типов)
	$(DEV) build api
	$(DEV) run --rm --no-deps api sh -c "ruff check . && ruff format --check ."
	$(DEV) build frontend
	$(DEV) run --rm --no-deps frontend sh -c "npm run lint && npm run typecheck"

logs: env ## Логи сервиса: make logs s=bot
	$(DEV) logs -f $(s)

prod: env ## На сервере: собрать и запустить прод
	$(PROD) up -d --build
