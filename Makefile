COMPOSE := docker compose -f docker-compose.yml
DEV := $(COMPOSE) -f docker-compose.dev.yml
PROD := $(COMPOSE) -f docker-compose.prod.yml

.DEFAULT_GOAL := help
.PHONY: help env dev down migrate test lint logs prod check-amd64 seed-dev

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

test: env ## pytest (backend) и vitest (frontend)
	$(DEV) build api
	$(DEV) run --rm api pytest
	$(DEV) build frontend
	$(DEV) run --rm --no-deps frontend npm test

lint: env ## ruff + eslint (и проверка типов)
	$(DEV) build api
	$(DEV) run --rm --no-deps api sh -c "ruff check . && ruff format --check ."
	$(DEV) build frontend
	$(DEV) run --rm --no-deps frontend sh -c "npm run lint && npm run typecheck"

seed-dev: env ## Тестовые пользователи (только разработка, стек должен быть запущен)
	$(DEV) exec api python -m app.seed_dev

logs: env ## Логи сервиса: make logs s=bot
	$(DEV) logs -f $(s)

check-amd64: ## Проверить, что образы собираются под amd64 (сервер)
	docker buildx build --platform linux/amd64 --target dev --output type=cacheonly backend
	docker buildx build --platform linux/amd64 --target prod --output type=cacheonly backend
	docker buildx build --platform linux/amd64 --target dev --output type=cacheonly frontend
	docker buildx build --platform linux/amd64 --target prod --output type=cacheonly frontend

prod: env ## На сервере: собрать и запустить прод
	$(PROD) up -d --build
	# Caddyfile примонтирован файлом: без пересоздания изменения после git pull не применятся
	$(PROD) up -d --force-recreate --no-deps caddy
