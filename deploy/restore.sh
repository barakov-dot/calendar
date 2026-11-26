#!/bin/sh
# Восстановление из копии: make restore file=backups/buh-....tar.gz
#
# Текущая база не удаляется, а переименовывается, текущий config сохраняется
# в архив. Удалите их вручную, когда убедитесь, что всё восстановилось.
set -eu
umask 077
archive=${1:-}
if [ -z "$archive" ] || [ ! -f "$archive" ]; then
    echo "Укажите файл копии: make restore file=backups/buh-ДАТА.tar.gz" >&2
    exit 1
fi
archive=$(cd "$(dirname "$archive")" && pwd)/$(basename "$archive")
cd "$(dirname "$0")/.."
COMPOSE=${COMPOSE:-"docker compose -f docker-compose.yml -f docker-compose.prod.yml"}
stamp=$(date +%Y%m%d_%H%M%S)

echo "База и настройки будут заменены данными из $archive."
echo "Сервис на это время остановится. Продолжить? Введите yes:"
read -r answer
[ "$answer" = "yes" ] || { echo "Отменено"; exit 1; }

work=$(mktemp -d)
cleanup() {
    find "$work" -type f -delete
    find "$work" -depth -type d -exec rmdir {} \;
}
trap cleanup EXIT
tar -xzf "$archive" -C "$work"
test -s "$work/db.dump" || { echo "В архиве нет дампа базы" >&2; exit 1; }

$COMPOSE up -d --wait db

# Сначала разворачиваем копию в отдельную базу: при ошибке рабочая не тронута.
$COMPOSE exec -T db sh -c '
    psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres \
        -c "DROP DATABASE IF EXISTS \"${POSTGRES_DB}_restore\"" \
        -c "CREATE DATABASE \"${POSTGRES_DB}_restore\""'
$COMPOSE exec -T db sh -c \
    'pg_restore --exit-on-error --no-owner -U "$POSTGRES_USER" -d "${POSTGRES_DB}_restore"' \
    < "$work/db.dump"

$COMPOSE stop api bot worker
$COMPOSE exec -T db sh -c '
    psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres \
        -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '"'"'$POSTGRES_DB'"'"'" \
        -c "ALTER DATABASE \"$POSTGRES_DB\" RENAME TO \"${POSTGRES_DB}_before_'"$stamp"'\"" \
        -c "ALTER DATABASE \"${POSTGRES_DB}_restore\" RENAME TO \"$POSTGRES_DB\""' > /dev/null

if [ -d "$work/config" ]; then
    mkdir -p backups
    tar -czf "backups/config-before-restore-$stamp.tar.gz" config
    cp -R "$work/config/." config/
fi

$COMPOSE up -d --wait
echo "Восстановлено. Прежняя база: <имя>_before_$stamp, прежний config — в backups/."
