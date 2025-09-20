#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

: "${NMS_HG_PATH:=$(grep '^NMS_HG_PATH=' .env 2>/dev/null | cut -d= -f2-)}"
if [[ -z "${NMS_HG_PATH:-}" ]]; then
  echo "[ERR] NMS_HG_PATH not set in .env"
  exit 1
fi

echo "[WATCH] monitoring $NMS_HG_PATH"
echo "[WATCH] requires inotifywait (inotify-tools). Ctrl+C to stop."

# Run once at start (so UI isn't empty)
bash "$ROOT/scripts/run_pipeline.sh" || true

if command -v inotifywait >/dev/null 2>&1; then
  while inotifywait -e close_write,modify,move,attrib "$NMS_HG_PATH"; do
    echo "[WATCH] change detected -> pipeline"
    bash "$ROOT/scripts/run_pipeline.sh" || true
  done
else
  echo "[WARN] inotifywait not found; polling every 15s"
  prev=""
  while true; do
    cur="$(stat -c %Y "$NMS_HG_PATH" 2>/dev/null || echo 0)"
    if [[ "$cur" != "$prev" ]]; then
      prev="$cur"
      echo "[WATCH] change detected (poll) -> pipeline"
      bash "$ROOT/scripts/run_pipeline.sh" || true
    fi
    sleep 15
  done
fi
