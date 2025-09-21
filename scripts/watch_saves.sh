#!/usr/bin/env bash
# Watches your NMS save directories for changes to *.hg and triggers
# scripts/runtime_refresh.sh (which handles decode/import + skip guard).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Load .env if present
if [[ -f .env ]]; then
  # shellcheck source=/dev/null
  source .env
fi

LOG_DIR=".cache/logs"
mkdir -p "$LOG_DIR"

REFRESH_SCRIPT="${ROOT}/scripts/runtime_refresh.sh"
if [[ ! -x "$REFRESH_SCRIPT" ]]; then
  echo "[watch] ERROR: ${REFRESH_SCRIPT} not found or not executable." >&2
  exit 1
fi

# NMS_SAVES_DIRS can be colon-separated for multiple dirs. Example:
# NMS_SAVES_DIRS="/path/one:/path two/with spaces:/another"
DEFAULT_SAVES="/mnt/Unlimited-Gaming/SteamLibrary/steamapps/compatdata/275850/pfx/drive_c/users/steamuser/Application Data/HelloGames/NMS/st_76561198065088580"
SAVES_RAW="${NMS_SAVES_DIRS:-$DEFAULT_SAVES}"

# Split colon-separated list into an array while preserving spaces in paths
IFS=':' read -r -a WATCH_DIRS <<< "$SAVES_RAW"
# Keep only existing dirs
FILTERED_DIRS=()
for d in "${WATCH_DIRS[@]}"; do
  if [[ -d "$d" ]]; then
    FILTERED_DIRS+=("$d")
  else
    echo "[watch] WARN: not a directory, skipping: $d"
  fi
done

if [[ ${#FILTERED_DIRS[@]} -eq 0 ]]; then
  echo "[watch] ERROR: No valid save directories to watch." >&2
  exit 1
fi

echo "[watch] watching ${#FILTERED_DIRS[@]} dir(s) for *.hg changes:"
for d in "${FILTERED_DIRS[@]}"; do
  echo "        - $d"
fi

# Debounce settings
DEBOUNCE_SECS="${NMS_WATCH_DEBOUNCE_SECS:-2}"
last_run=0

trigger_refresh() {
  local now
  now="$(date +%s)"
  if (( now - last_run < DEBOUNCE_SECS )); then
    return 0
  fi
  echo "[watch] change detected → running runtime_refresh.sh"
  # Log refresh output separately; watcher.log is handled by dev_server.sh
  "${REFRESH_SCRIPT}" >> "${LOG_DIR}/watcher.refresh.log" 2>&1 || {
    echo "[watch] ERROR: refresh failed; see ${LOG_DIR}/watcher.refresh.log" >&2
  }
  last_run="$(date +%s)"
}

# Prefer inotify if available
if command -v inotifywait >/dev/null 2>&1; then
  echo "[watch] using inotifywait (recursive)."
  # Start a single inotify stream over all dirs
  # Events: create, move, close_write cover new/updated saves
  inotifywait -m -r \
    -e create -e move -e close_write \
    --format '%w%f' \
    -- "${FILTERED_DIRS[@]}" | while IFS= read -r path; do
      # only react to .hg files
      if [[ "$path" == */save*.hg ]]; then
        trigger_refresh
      fi
    done
else
  echo "[watch] inotifywait not found; falling back to polling (5s)."
  # Poll hash of (*.hg path + mtime) across watched dirs
  last_hash=""
  while true; do
    # Build a stable signature of current .hg set
    current_hash="$(
      find "${FILTERED_DIRS[@]}" -type f -name 'save*.hg' -printf '%p %T@\n' \
        | sort \
        | sha256sum \
        | awk '{print $1}'
    )"
    if [[ "$current_hash" != "$last_hash" ]]; then
      trigger_refresh
      last_hash="$current_hash"
    fi
    sleep 5
  done
fi
