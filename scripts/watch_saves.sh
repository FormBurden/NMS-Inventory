#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a; source "$ENV_FILE"; set +a
else
  echo "[watch] WARN: .env not found at $ENV_FILE – using environment/defaults."
fi

# Required (from .env or environment)
: "${NMS_SAVE_ROOT:?Set NMS_SAVE_ROOT in .env}"
: "${NMS_PROFILE:?Set NMS_PROFILE in .env}"

# Optional
WATCH_FILE="${NMS_WATCH_FILE:-save2.hg}"
DEBOUNCE_SEC="${NMS_WATCH_DEBOUNCE:-3}"
STARTUP_DELAY="${NMS_WATCH_STARTUP_DELAY:-60}"


PROFILE_DIR="$NMS_SAVE_ROOT/$NMS_PROFILE"
TARGET="$PROFILE_DIR/$WATCH_FILE"

if ! command -v inotifywait >/dev/null 2>&1; then
  echo "[watch] ERROR: inotifywait not found. Install 'inotify-tools' and re-run."
  exit 1
fi

if [[ ! -d "$PROFILE_DIR" ]]; then
  echo "[watch] ERROR: Profile dir not found: $PROFILE_DIR"
  exit 1
fi

echo "[watch] watching: $TARGET"
echo "[watch] press Ctrl-C to stop"

last_run=0
start_time="$(date +%s)"


while true; do
  # wake up on any activity under the profile dir
  inotifywait -e close_write,modify,move,create,attrib "$PROFILE_DIR" >/dev/null 2>&1 || true
  [[ -f "$TARGET" ]] || continue

  now=$(date +%s)
  # Startup gate: ignore early events while NMS is booting
  if (( now - start_time < STARTUP_DELAY )); then
    remain=$(( STARTUP_DELAY - (now - start_time) ))
    echo "[watch] startup gate active (${remain}s left) — ignoring event"
    continue
  fi

  (( now - last_run < DEBOUNCE_SEC )) && continue

  echo "[watch] change detected → runtime_refresh.sh"
  if ( cd "$REPO_ROOT" && ./scripts/runtime_refresh.sh ); then
    echo "[watch] refresh ok"
  else
    echo "[watch] refresh failed"
  fi

  last_run=$now
done
