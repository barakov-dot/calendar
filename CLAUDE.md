# CLAUDE.md — Платёжный календарь бухгалтерской компании

## О проекте
Внутренний сервис аутсорсинговой бухгалтерской компании (~40 клиентов, несколько бухгалтеров).
Показывает налоговые сроки и суммы к уплате по каждой компании клиента, рассылает напоминания в Telegram.
Работает как **Telegram Mini App** и как **сайт** (один и тот же фронтенд).

Полный план работ — в `PLAN.md`. Работаем строго по фазам и чек-листам оттуда, отмечаем выполненное `[x]`.
Не переходить к следующей фазе без команды пользователя.

## Окружение (важно!)
- **Разработка:** macOS на Apple Silicon (M5, arm64), Docker Desktop. Всё запускается **только в Docker** — на Mac не ставим Python/Node/Postgres.
- **Продакшен:** Ubuntu на **x86_64 (amd64)**, Docker + docker compose.
- Поэтому:
  - использовать только официальные мультиархитектурные образы (`python:3.12-slim`, `postgres:16`, `node:22-slim`, `nginx:1-alpine`);
  - не фиксировать `platform:` в compose и не тянуть бинарники под одну архитектуру;
  - образы для прода **собираются на сервере** (`docker compose build`), а не переносятся с Mac;
  - `node_modules` фронтенда живут в именованном docker-volume, а не монтируются с Mac;
  - проверка совместимости: `docker buildx build --platform linux/amd64 ...` должна проходить.
- Часовой пояс бизнеса: `Europe/Moscow`. В БД даты сроков — `date`, моменты времени — `timestamptz` (UTC).

## Роли
- `admin` — владелец бухгалтерской компании. Видит всё, приглашает бухгалтеров, переназначает компании, управляет настройками приложения.
- `accountant` — бухгалтер. Видит и редактирует **только свои** компании (`companies.accountant_id = user.id`). Ставит статусы «Оплачено» / «Сдано» / «Не требуется».
- `assistant` — помощник бухгалтера. Видит все компании, задачи, суммы и внутренние комментарии, **ничего не меняет**. Приглашает админ.
- `client` — клиент. Видит **только привязанные к нему** компании (через `company_members`) и только задачи с `client_visible = true` (платежи и отчёты со статусами). По умолчанию **только просмотр** и напоминания о платежах.
  - Исключение: если у клиента `company_members.can_mark_paid = true` («Клиент платит сам»), он может перевести платёжную задачу `planned → paid`. Статус ставится сразу, бухгалтер получает уведомление и может отменить. Флаг задаётся на каждого клиента отдельно, меняет его только бухгалтер этой компании или админ.

Приглашения (бухгалтеров, помощников и клиентов) выдаёт **только админ**.

Доступ только по приглашению. Пользователь без приглашения, нажавший /start, получает «Доступ по приглашению».

## Стек
- Backend: Python 3.12, FastAPI, SQLAlchemy 2 (async, asyncpg), Alembic, PostgreSQL 16, Pydantic v2
- Бот: aiogram 3, **long polling** (не webhook), отдельный контейнер `bot`; поддержка SOCKS5 через `aiohttp-socks`
- Рассылки: отдельный контейнер `worker` с APScheduler
- Frontend: React + Vite + TypeScript, Tailwind, @telegram-apps/sdk-react, TanStack Query
- Прод: контейнер `web` (nginx) раздаёт собранный фронтенд и проксирует `/api` по HTTP; домен и HTTPS — на обратном прокси nginx владельца (вне проекта). Caddy не используется.

## Настройки приложения
- **Инфраструктурные секреты** — в `.env` (нужны до старта приложения): `DATABASE_URL`, `POSTGRES_*`, `BOT_TOKEN`, `JWT_SECRET`, `ADMIN_TELEGRAM_ID`, `APP_ENV` (dev|prod), `HTTP_BIND`/`HTTP_PORT` (прод), `SETTINGS_PATH`, `APP_UID`/`APP_GID` (пользователь в backend-контейнерах). Опционально `TELEGRAM_PROXY_URL` — запасной прокси для первого запуска.
- **Все остальные настройки** — в JSON-файле `settings.json` (путь из `SETTINGS_PATH`, по умолчанию `/app/config/settings.json`), лежит в общем volume `./config`, который монтируется в `api`, `bot`, `worker`. В git не коммитится, в репозитории есть `config/settings.example.json`.
- Настройки редактируются **через веб** (страница «Настройки», только admin) и вручную в файле.
- Доступ — только через модуль `app/core/settings_store.py`:
  - схема — Pydantic-модель; при чтении валидируется, при ошибке — понятное сообщение в лог, работаем на последней валидной версии;
  - запись атомарная: временный файл → `fsync` → `os.replace`; блокировка `fcntl.flock`; права файла `600`;
  - перед записью — бэкап предыдущей версии в `config/backups/settings-<timestamp>.json` (хранить 20 последних);
  - `bot` и `worker` следят за `mtime` файла (раз в 5 с) и применяют изменения без перезапуска (например, переподключаются через новый прокси);
  - секреты (пароль прокси, ключи DaData) в API отдаются на фронтенд только маской `••••`; пустое поле при сохранении = «не менять».

## Структура репозитория
```
backend/
  app/
    api/          # FastAPI роутеры
    bot/          # aiogram: хендлеры, клавиатуры, запуск polling
    core/         # конфиг (.env), settings_store (JSON), безопасность (initData, JWT), права
    models/       # SQLAlchemy модели
    schemas/      # Pydantic схемы
    services/
      rules/      # движок налоговых правил
      calendar/   # производственный календарь и переносы сроков
      notify/     # формирование и отправка уведомлений
      telegram/   # фабрика Bot/сессии с учётом прокси из настроек
      dadata/     # клиент DaData
    worker.py     # планировщик рассылок
  alembic/
  tests/
  Dockerfile
frontend/
  Dockerfile      # multi-stage: dev (vite) и build (nginx со статикой)
rules/            # налоговые правила в YAML (по году)
data/calendar/    # производственный календарь по годам (JSON)
config/           # settings.json (gitignore), settings.example.json, backups/
deploy/           # пример конфигурации nginx, инструкция по развёртыванию на Ubuntu, скрипт бэкапа
docker-compose.yml        # общая часть
docker-compose.dev.yml    # Mac: hot reload, порты наружу, dev-логин
docker-compose.prod.yml   # Ubuntu: web (nginx) за обратным прокси, restart: unless-stopped
Makefile                  # короткие команды
```

## Жёсткие правила разработки
1. **Права доступа проверяются на бэкенде в каждом запросе** через `core/permissions.py` (`get_accessible_company_ids(db, user)`). Никогда не полагаться на фронтенд.
2. **Налоговые правила — данные, а не код.** Сроки в `rules/*.yaml`, у каждого правила обязательно поле `source` (статья НК РФ / письмо ФНС). Python — только для нестандартных расчётов (патент, НДФЛ за 23–31 декабря, разбивка НДС на 1/3).
3. **Перенос сроков** (п. 7 ст. 6.1 НК РФ): выходной/праздник → ближайший следующий рабочий день по производственному календарю. Логика — в `services/calendar`, покрыта тестами.
4. **Генерация задач идемпотентна.** Ключ: `(company_id, rule_code, period_key, part)`. Повторная генерация не трогает статусы, суммы и комментарии.
5. Суммы налогов вводит бухгалтер. Сервис налоги **не считает**, но разбивает квартальную сумму НДС на 3 платежа.
6. Деньги — в копейках (`bigint`), не во float.
7. Все обращения к Telegram API (бот, воркер, проверка прокси) — только через `services/telegram`, который берёт прокси из настроек. Никаких `Bot(token)` в обход фабрики.
8. Dev-логин (выбор пользователя без Telegram) существует **только при `APP_ENV=dev`**; в prod эндпоинт не регистрируется вообще. Есть тест на это.
9. Секреты не коммитить: `.env`, `config/settings.json`, `config/backups/` — в `.gitignore`. В репозитории — `.env.example` и `config/settings.example.json` с заглушками.
10. Каждое изменение поведения — с тестом. Для сроков есть «золотые» тесты с реальными датами 2026 года (PLAN.md, раздел 8).
11. Тексты интерфейса и уведомлений — на русском.

## Команды (через Makefile)
```
make dev          # docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
make down
make migrate      # alembic upgrade head в контейнере api
make test         # pytest в контейнере api
make lint         # ruff + eslint
make gen          # перегенерировать задачи по всем компаниям
make calendar year=2027  # загрузить производственный календарь из data/calendar
make export year=2026    # календарь тестовых компаний в Excel (data/exports)
make logs s=bot   # логи сервиса
make seed-dev     # тестовые пользователи и компании (только dev, стек запущен)
make check-amd64  # docker buildx build --platform linux/amd64 для backend и frontend
# на сервере:
make prod         # docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
make backup       # pg_dump + копия config/ в ./backups
make restore file=backups/buh-....tar.gz   # восстановление с подтверждением
```
