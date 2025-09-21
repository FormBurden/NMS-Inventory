#!/usr/bin/env bash
set -euo pipefail

# Requires: inotify-tools (Arch/Manjaro: sudo pacman -S inotify-tools)
command -v inotifywait >/dev/null 2>&1 || { echo "[err] inotifywait not found (install inotify-tools)"; exit 2; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"
[[ -f "$ENV_FILE" ]] || { echo "[err] Missing .env at $ENV_FILE"; exit 2; }

set -a; source "$ENV_FILE"; set +a
: "${NMS_SAVE_ROOT:?}"; : "${NMS_PROFILE:?}"

TARGET="$NMS_SAVE_ROOT/$NMS_PROFILE/save2.hg"
DIR="$(dirname "$TARGET")"
BASE="$(basename "$TARGET")"

echo "[watch] watching: $TARGET"
echo "[watch] press Ctrl-C to stop"

# simple debounce
last_run=0
debounce_sec=3

while true; do
  inotifywait -e close_write,modify,move,create,attrib "$DIR" >/dev/null 2>&1 || true
  # something changed; check our file
  if [[ -f "$TARGET" ]]; then
    now=$(date +%s)
    if (( now - last_run < debounce_sec )); then
      continue
    fi
    echo "[watch] change detected → running import_latest.sh"
    ( cd "$REPO_ROOT" && ./scripts/import_latest.sh ) || echo "[watch] import failed (see above)"
    last_run=$now
  fi
done
