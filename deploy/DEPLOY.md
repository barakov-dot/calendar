# Развёртывание на Ubuntu (x86_64)

> Черновик (Фаза 0). Полная инструкция, резервные копии и мониторинг — в Фазе 7.

## 1. Подготовка сервера
1. Установить Docker Engine и compose plugin по [официальной инструкции](https://docs.docker.com/engine/install/ubuntu/).
2. Установить `git` и `make`: `sudo apt install git make`.
3. Направить DNS-запись домена на ваш обратный прокси nginx (он принимает 80 и 443).

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
| `HTTP_BIND`, `HTTP_PORT` | адрес и порт, на которые ваш nginx будет слать запросы (по умолчанию `127.0.0.1:8080`) |
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

Проверка на сервере (порт — ваш `HTTP_PORT`):

```bash
curl http://127.0.0.1:8080/api/health
```

Должно вернуться `{"status":"ok","database":"ok"}`.

## Обратный прокси nginx
Контейнер `web` отвечает только по HTTP. Домен, сертификат и HTTPS настраиваются в вашем
nginx; пример — [nginx.example.conf](nginx.example.conf). Проверьте:
`https://<домен>/api/health`.

HTTPS обязателен: без него Telegram не откроет Mini App.

Если nginx стоит **не на этом сервере** или работает в отдельной Docker-сети, укажите в
`HTTP_BIND` внутренний IP сервера и закройте этот порт файрволом от всех, кроме прокси.
Docker открывает порты в обход `ufw`, поэтому привязывайте порт именно к внутреннему адресу.

После этого на странице «Настройки» → «Telegram и прокси» впишите адрес Mini App
`https://<домен>/`: без него в сообщениях бота не будет кнопки «Открыть календарь».

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
