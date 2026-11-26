#!/bin/sh
# Резервная копия: дамп базы и каталог config (settings.json и его копии).
# Файл .env сюда не входит — сохраните его отдельно один раз.
#
# Запуск на сервере: make backup   (или из cron: /путь/к/проекту/deploy/backup.sh)
# Настройки (в .env или переменных окружения):
#   BACKUP_DIR        каталог копий, по умолчанию ./backups
#   BACKUP_KEEP_DAYS  сколько дней хранить, по умолчанию 30
#   BACKUP_REMOTE     куда копировать вне сервера, например user@host:/srv/buh-backups
set -eu
umask 077
cd "$(dirname "$0")/.."

setting() {
    # значение из окружения, иначе из .env
    eval "value=\${$1:-}"
    if [ -z "$value" ] && [ -f .env ]; then
        value=$(sed -n "s/^$1=//p" .env | tail -n 1)
    fi
    printf '%s' "${value:-$2}"
}

BACKUP_DIR=$(setting BACKUP_DIR "$PWD/backups")
KEEP_DAYS=$(setting BACKUP_KEEP_DAYS 30)
REMOTE=$(setting BACKUP_REMOTE "")
COMPOSE=${COMPOSE:-"docker compose -f docker-compose.yml -f docker-compose.prod.yml"}

case $KEEP_DAYS in
    '' | *[!0-9]* | 0) echo "BACKUP_KEEP_DAYS должно быть числом от 1" >&2; exit 1 ;;
esac

mkdir -p "$BACKUP_DIR"
name="buh-$(date +%Y%m%d-%H%M%S).tar.gz"
work=$(mktemp -d "$BACKUP_DIR/.work.XXXXXX")
cleanup() {
    rm -f "$work/db.dump" "$work/archive.tar.gz"
    rmdir "$work"
}
trap cleanup EXIT

$COMPOSE exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "$work/db.dump"
test -s "$work/db.dump" || { echo "Пустой дамп базы" >&2; exit 1; }
tar -czf "$work/archive.tar.gz" --exclude='*.lock' --exclude='*_status.json' \
    -C "$work" db.dump -C "$PWD" config
# архив должен читаться, прежде чем считаться копией
tar -tzf "$work/archive.tar.gz" > /dev/null
mv "$work/archive.tar.gz" "$BACKUP_DIR/$name"
echo "Копия создана: $BACKUP_DIR/$name"

# старые копии удаляются только после успешного создания новой
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'buh-*.tar.gz' -mtime +"$KEEP_DAYS" -delete

if [ -n "$REMOTE" ]; then
    rsync -a "$BACKUP_DIR/$name" "$REMOTE/"
    echo "Скопировано на $REMOTE"
else
    echo "Внимание: BACKUP_REMOTE не задан, копии вне сервера нет" >&2
fi
