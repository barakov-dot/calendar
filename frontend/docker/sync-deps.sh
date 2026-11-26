#!/bin/sh
# node_modules лежит в именованном томе: переустанавливаем, только если изменился package-lock.json.
set -e
if ! sha256sum -c --status node_modules/.lock-hash 2>/dev/null; then
  npm ci --no-audit --no-fund
  sha256sum package-lock.json > node_modules/.lock-hash
fi
exec "$@"
