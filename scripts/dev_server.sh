#!/usr/bin/env bash
set -euo pipefail

# Root of repo
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Sanity checks (watcher expects NMS_HG_PATH in .env)
if [[ ! -f .env ]]; then
  echo "[ERR] .env is missing at repo root. Copy .env.example and set values." >&2
  exit 1
fi

# Start the save-file watcher first (runs pipeline on startup + on changes)
echo "[*] starting watcher: scripts/watch_saves.sh"
bash "$ROOT/scripts/watch_saves.sh" &
WATCH_PID=$!

cleanup() {
  echo "[*] stopping watcher ($WATCH_PID)…"
  kill "$WATCH_PID" 2>/dev/null || true
  wait "$WATCH_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Now run the PHP dev server
echo "[*] PHP dev server: http://localhost:8080  (docroot=public)"
php -S localhost:8080 -t public
