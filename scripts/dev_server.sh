#!/usr/bin/env bash
set -euo pipefail

# ────────────────────────────────────────────────────────────────────────────────
# NMS-Inventory Dev Server (original behavior + EDTB-style logs + fingerprint)
# ────────────────────────────────────────────────────────────────────────────────

# Repo & env
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "[err] Missing .env at $ENV_FILE"
  exit 2
fi
set -a; source "$ENV_FILE"; set +a
: "${NMS_DECODER:=$REPO_ROOT/scripts/python/nms_hg_decoder.py}"
: "${NMS_SAVES_DIRS:=${NMS_SAVE_ROOT%/}/${NMS_PROFILE}}"

# Defaults / docroot / host:port
HOST="${NMS_DEV_HOST:-localhost}"   # UX: we *print* localhost
PORT="${NMS_DEV_PORT:-8080}"
DOCROOT="$REPO_ROOT/public"; [[ -d "$DOCROOT" ]] || DOCROOT="$REPO_ROOT"

# We bind the PHP server to IPv4 explicitly so curl http://localhost:8080 works
BIND_HOST="127.0.0.1"
PRINT_HOST="localhost"

# ────────────────────────────────────────────────────────────────────────────────
# EDTB-style logging (per-run folder with access/php/server logs)
# ────────────────────────────────────────────────────────────────────────────────
LOG_ROOT="${NMS_LOG_DIR:-$REPO_ROOT/logs}"
TS_START="$(date +"%Y%m%d-%H%M%S")"
RUN_DIR="$LOG_ROOT/DEV/$TS_START"
mkdir -p "$RUN_DIR"

ACCESS_LOG="$RUN_DIR/access.log"
SERVER_LOG="$RUN_DIR/server.log"
PHP_LOG="$RUN_DIR/php.log"

PIPE="$RUN_DIR/.dev_stream.pipe"
rm -f "$PIPE"; mkfifo "$PIPE"

awk \
  -v access_log="$ACCESS_LOG" \
  -v php_log="$PHP_LOG" \
  -v server_log="$SERVER_LOG" '
  function strip_ansi(s){ gsub(/\x1B\[[0-9;]*[A-Za-z]/,"",s); return s }
  function c_red(){ return "\033[31;1m"} function c_yel(){ return "\033[33;1m"}
  function c_mag(){ return "\033[35;1m"} function c_rst(){ return "\033[0m"}
  function is_access(s){
    return (s ~ /\[[0-9]{3}\]: (GET|POST|HEAD|PUT|DELETE|PATCH|OPTIONS) /) \
        || (s ~ /" (GET|POST|HEAD|PUT|DELETE|PATCH|OPTIONS) .*" [0-9]{3} /) \
        || (s ~ /(Accepted|Closing)$/)
  }
  function is_php_warn(s){ return s ~ /PHP (Warning|Deprecated)/ }
  function is_php_err(s){ return s ~ /PHP (Fatal error|Parse error|Recoverable fatal error|Error)|Uncaught / }
  function is_php_notice(s){ return s ~ /PHP Notice/ }
  {
    raw=$0; plain=strip_ansi(raw)
    print plain >> server_log; fflush(server_log)
    if (is_access(plain)) { print plain >> access_log; fflush(access_log) }
    if (is_php_warn(plain) || is_php_err(plain) || is_php_notice(plain)) { print plain >> php_log; fflush(php_log) }
    if (is_php_err(plain)) { print c_red() raw c_rst(); next }
    if (is_php_warn(plain)) { print c_yel() raw c_rst(); next }
    code=-1
    if (match(plain, /\[([0-9]{3})\]:/, m)) code=m[1]+0
    else if (match(plain, /" ([0-9]{3}) /, m2)) code=m2[1]+0
    if (code>=500) { print c_red() raw c_rst(); next }
    if (code>=400) { print c_mag() raw c_rst(); next }
  }
' < "$PIPE" &
LOGGER_PID=$!

echo "[dev] logs → $RUN_DIR"

# ────────────────────────────────────────────────────────────────────────────────
# Preflight: decoder + .fingerprint rule, then importer (only when needed)
# ────────────────────────────────────────────────────────────────────────────────
(
  # Preflight: use the unified runtime refresh (folder-based .fingerprint)
  exec >"$PIPE" 2>&1
  echo "[dev] preflight refresh via runtime_refresh.sh"
  if ( cd "$REPO_ROOT" && ./scripts/runtime_refresh.sh ); then
    echo "[dev] preflight refresh ok"
  else
    echo "[dev] WARN: runtime_refresh failed; continuing to start server."
  fi
) &

PRE_PID=$!


# ────────────────────────────────────────────────────────────────────────────────
# Watcher (unchanged) — pipe output into logger
# ────────────────────────────────────────────────────────────────────────────────
WATCH_PID=""
if [[ -x "$REPO_ROOT/scripts/watch_saves.sh" ]]; then
  echo "[dev] starting watcher: $REPO_ROOT/scripts/watch_saves.sh"
  bash "$REPO_ROOT/scripts/watch_saves.sh" >"$PIPE" 2>&1 &
  WATCH_PID=$!
fi

# ────────────────────────────────────────────────────────────────────────────────
# Dev server — bind to 127.0.0.1 to satisfy http://localhost:8080/*
# ────────────────────────────────────────────────────────────────────────────────
echo "[dev] starting server on http://${PRINT_HOST}:${PORT}"
echo "[dev] serving on http://${PRINT_HOST}:${PORT} (docroot: $(basename "$DOCROOT"))"

if [[ -n "${NMS_DEV_CMD:-}" ]]; then
  ( cd "$DOCROOT" && eval "$NMS_DEV_CMD" ) >"$PIPE" 2>&1 &
  SERVER_PID=$!
else
  if command -v php >/dev/null 2>&1; then
    ( cd "$DOCROOT" && php -S "${BIND_HOST}:${PORT}" -t "$DOCROOT" ) >"$PIPE" 2>&1 &
  else
    echo "[warn] php not found; falling back to python http.server (PHP endpoints will NOT work)."
    ( cd "$DOCROOT" && python3 -m http.server "$PORT" --bind "$BIND_HOST" ) >"$PIPE" 2>&1 &
  fi
  SERVER_PID=$!
fi

# Optional: tiny health check to catch early bind failures (non-fatal; logs hint)
for i in 1 2 3 4 5; do
  if curl -fsS --max-time 1 "http://127.0.0.1:${PORT}/" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

trap '
  echo
  echo "[dev] shutting down..."

  # stop children in order
  [[ -n "${WATCH_PID:-}" ]] && kill "$WATCH_PID" 2>/dev/null || true
  [[ -n "${SERVER_PID:-}" ]] && kill "$SERVER_PID" 2>/dev/null || true
  [[ -n "${PRE_PID:-}" ]] && kill "$PRE_PID" 2>/dev/null || true
  [[ -n "${LOGGER_PID:-}" ]] && kill "$LOGGER_PID" 2>/dev/null || true

  # remove fifo before moving logs
  [[ -p "$PIPE" ]] && rm -f "$PIPE"

  # finalize log dir name with exact stop time
  TS_STOP="$(date +"%Y%m%d-%H%M%S")"
  FINAL_DIR="$LOG_ROOT/DEV/$TS_STOP"
  if [[ -d "$RUN_DIR" && "$FINAL_DIR" != "$RUN_DIR" ]]; then
    if mv "$RUN_DIR" "$FINAL_DIR" 2>/dev/null; then
      echo "[dev] logs finalized → $FINAL_DIR"
    else
      # fallback if FINAL_DIR already exists (highly unlikely)
      FINAL_DIR="${RUN_DIR}.final"
      mv "$RUN_DIR" "$FINAL_DIR" 2>/dev/null || true
      echo "[dev] logs finalized → $FINAL_DIR"
    fi
  fi

  wait
  exit 0
' INT TERM



echo "[dev] server pid = $SERVER_PID"
echo "[dev] ready. Press Ctrl-C to stop."
wait "$SERVER_PID"
