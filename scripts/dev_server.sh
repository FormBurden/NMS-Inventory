#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Load .env if present
if [[ -f .env ]]; then
  # shellcheck source=/dev/null
  source .env
fi

PHP_ADDR="${PHP_ADDR:-localhost}"
PHP_PORT="${PHP_PORT:-8080}"
PHP_DOCROOT="${PHP_DOCROOT:-public}"

echo "[dev] preflight refresh (decode/import if needed)"
scripts/runtime_refresh.sh

echo "[dev] starting watcher: ${ROOT}/scripts/watch_saves.sh"
scripts/watch_saves.sh >> .cache/logs/watcher.log 2>&1 & 
WATCH_PID=$!

echo "[dev] serving on http://${PHP_ADDR}:${PHP_PORT} (docroot: ${PHP_DOCROOT})"
php -S "${PHP_ADDR}:${PHP_PORT}" -t "${PHP_DOCROOT}" &
PHP_PID=$!

# Clean shutdown
trap 'echo "[dev] stopping..."; kill ${PHP_PID} ${WATCH_PID} 2>/dev/null || true; wait || true' INT TERM

# Wait for PHP (foreground-ish)
wait ${PHP_PID}
