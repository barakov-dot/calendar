# Развёртывание на Ubuntu (x86_64)

> Черновик (Фаза 0). Полная инструкция, резервные копии и мониторинг — в Фазе 7.

## 1. Подготовка сервера
1. Установить Docker Engine и compose plugin по [официальной инструкции](https://docs.docker.com/engine/install/ubuntu/).
2. Установить `git` и `make`: `sudo apt install git make`.
3. Открыть входящие порты 80 и 443.
4. Направить DNS-запись домена на IP сервера.

## 2. Код и настройки
```bash
git clone https://github.com/barakov-dot/calendar.git
```
```bash
cd calendar
```
```bash
cp .env.example .env && chmod 600 .env
```

В `.env` заменить:

| Переменная | Что вписать |
|---|---|
| `POSTGRES_PASSWORD` и пароль внутри `DATABASE_URL` | один и тот же случайный пароль: `openssl rand -hex 24` |
| `APP_DOMAIN` | домен сервиса без `https://` |
| `APP_UID`, `APP_GID` | вывод команд `id -u` и `id -g` |
| `BOT_TOKEN` | токен от @BotFather |
| `JWT_SECRET` | `openssl rand -hex 32` |
| `ADMIN_TELEGRAM_ID` | ваш числовой Telegram ID |
| `TELEGRAM_PROXY_URL` | при необходимости, до настройки прокси в вебе |

`APP_ENV` в проде принудительно равен `prod` (задан в `docker-compose.prod.yml`).

Пароль базы применяется только при первом запуске, когда создаётся том `pgdata`.

## 3. Запуск
```bash
make prod
```

Образы собираются прямо на сервере. Миграции базы применяются при старте `api`.

Проверка (подставьте свой домен): `https://<домен>/api/health` должен вернуть
`{"status":"ok","database":"ok"}`.

Первый вход: отправьте боту `/start`, дайте согласие, затем откройте сайт и нажмите
«Войти через Telegram». Прокси, DaData и ссылку на политику обработки данных настройте
на странице «Настройки».

## 4. Обновление
```bash
git pull && make prod
```

## 5. Диагностика
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f --tail=100
```

## Будет добавлено в Фазе 7
Настройка Mini App в BotFather, `deploy/backup.sh` и восстановление, мониторинг.
