#!/usr/bin/env bash
set -euo pipefail

command -v inotifywait >/dev/null 2>&1 || { echo "[err] inotifywait not found (install inotify-tools)"; exit 2; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"
[[ -f "$ENV_FILE" ]] || { echo "[err] Missing .env at $ENV_FILE"; exit 2; }

set -a; source "$ENV_FILE"; set +a
: "${NMS_SAVE_ROOT:?}"; : "${NMS_PROFILE:?}"

TARGET="$NMS_SAVE_ROOT/$NMS_PROFILE/save2.hg"
DIR="$(dirname "$TARGET")"

echo "[watch] watching: $TARGET"
echo "[watch] press Ctrl-C to stop"

last_run=0
debounce_sec=3

while true; do
  inotifywait -e close_write,modify,move,create "$DIR" >/dev/null 2>&1 || true
  [[ -f "$TARGET" ]] || continue
  now=$(date +%s)
  (( now - last_run < debounce_sec )) && continue
  echo "[watch] change detected → import_latest.sh"
  ( cd "$REPO_ROOT" && ./scripts/import_latest.sh ) && echo "[watch] import ok" || echo "[watch] import failed"
  last_run=$now
done
