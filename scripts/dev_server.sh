#!/usr/bin/env bash
set -euo pipefail

# Root of the repo (this script lives in scripts/)
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Defaults (override by exporting HOST/PORT/DOCROOT if you like)
HOST="${HOST:-localhost}"
PORT="${PORT:-8080}"
DOCROOT="${DOCROOT:-public}"

WATCHER="$ROOT_DIR/scripts/watch_saves.sh"

# Start the watcher in the background (if present)
if [[ -x "$WATCHER" || -f "$WATCHER" ]]; then
  echo "[dev] starting watcher: $WATCHER"
  "$WATCHER" &
  WATCH_PID=$!
  # Ensure watcher is cleaned up on exit
  cleanup() { kill "$WATCH_PID" 2>/dev/null || true; }
  trap cleanup EXIT INT TERM
else
  echo "[dev] watcher not found at $WATCHER (skipping)"
fi

# Start PHP’s built-in server in the foreground
echo "[dev] serving on http://$HOST:$PORT (docroot: $DOCROOT)"
exec php -S "$HOST:$PORT" -t "$ROOT_DIR/$DOCROOT"
