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

if [[ "${NMS_DEV_PRESERVE_WATCH_STARTUP_DELAY:-0}" != "1" ]]; then
  export NMS_WATCH_STARTUP_DELAY=0
else
  export NMS_WATCH_STARTUP_DELAY="${NMS_WATCH_STARTUP_DELAY:-0}"
fi
export NMS_WATCH_DEBOUNCE="${NMS_WATCH_DEBOUNCE:-2}"

SESSION_DIR="$REPO_ROOT/storage/runtime"
SESSION_STATE="$SESSION_DIR/nms_session.env"
SESSION_HISTORY="$SESSION_DIR/nms_sessions.tsv"
SESSION_HISTORY_LIMIT="${NMS_SESSION_HISTORY_LIMIT:-25}"
NMS_PROCESS_PATTERN="${NMS_PROCESS_PATTERN:-NMS.exe|NMS\.exe|No Man.?s Sky|Binaries/NMS}"
NMS_PROCESS_POLL_SEC="${NMS_PROCESS_POLL_SEC:-5}"

mkdir -p "$SESSION_DIR"

write_nms_session_state() {
  local active="$1"
  local started_at="$2"
  local ended_at="$3"
  local pid_list="$4"
  local tmp="$SESSION_STATE.tmp"

  {
    printf 'ACTIVE=%s\n' "$active"
    printf 'STARTED_AT=%s\n' "$started_at"
    printf 'ENDED_AT=%s\n' "$ended_at"
    printf 'PIDS=%s\n' "$pid_list"
    printf 'UPDATED_AT=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')"
  } > "$tmp"

  mv "$tmp" "$SESSION_STATE"
}

session_id_from_started_at() {
  printf '%s' "$1" | tr -cd '0-9'
}

trim_nms_session_history() {
  local limit="$SESSION_HISTORY_LIMIT"
  local tmp="$SESSION_HISTORY.tmp"

  if [[ ! "$limit" =~ ^[0-9]+$ || "$limit" -lt 1 ]]; then
    limit=25
  fi

  [[ -f "$SESSION_HISTORY" ]] || return 0

  {
    head -n 1 "$SESSION_HISTORY"
    tail -n +2 "$SESSION_HISTORY" | awk 'NF > 0' | tail -n "$limit"
  } > "$tmp"

  mv "$tmp" "$SESSION_HISTORY"
}

append_nms_session_history() {
  local started_at="$1"
  local ended_at="$2"
  local session_id

  [[ -n "$started_at" && -n "$ended_at" ]] || return 0
  session_id="$(session_id_from_started_at "$started_at")"
  [[ -n "$session_id" ]] || return 0

  if [[ ! -f "$SESSION_HISTORY" ]]; then
    printf 'session_id\tstarted_at\tended_at\tstatus\n' > "$SESSION_HISTORY"
  fi

  if grep -q "^${session_id}[[:space:]]" "$SESSION_HISTORY" 2>/dev/null; then
    trim_nms_session_history
    return 0
  fi

  printf '%s\t%s\t%s\tclosed\n' "$session_id" "$started_at" "$ended_at" >> "$SESSION_HISTORY"
  trim_nms_session_history
}

find_nms_processes() {
  pgrep -af -- "$NMS_PROCESS_PATTERN" 2>/dev/null \
    | grep -Ev 'pgrep|grep -E|dev_server\.sh|watch_saves\.sh|runtime_refresh\.sh|run_pipeline\.sh' \
    | awk '{print $1}' \
    | tr '\n' ' ' \
    | sed -E 's/[[:space:]]+$//'
}

watch_nms_process_session() {
  local active="0"
  local started_at=""
  local pid_list=""

  echo "[session] watching NMS process pattern: $NMS_PROCESS_PATTERN"

  while true; do
    pid_list="$(find_nms_processes || true)"

    if [[ -n "$pid_list" && "$active" != "1" ]]; then
      active="1"
      started_at="$(date '+%Y-%m-%d %H:%M:%S')"
      write_nms_session_state "1" "$started_at" "" "$pid_list"
      echo "[session] NMS started at $started_at pid(s): $pid_list"
    elif [[ -n "$pid_list" && "$active" == "1" ]]; then
      write_nms_session_state "1" "$started_at" "" "$pid_list"
    elif [[ -z "$pid_list" && "$active" == "1" ]]; then
      local ended_at
      ended_at="$(date '+%Y-%m-%d %H:%M:%S')"
      write_nms_session_state "0" "$started_at" "$ended_at" ""
      append_nms_session_history "$started_at" "$ended_at"
      echo "[session] NMS ended at $ended_at"
      active="0"
      started_at=""
    fi

    sleep "$NMS_PROCESS_POLL_SEC"
  done
}

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
    if (plain ~ /^\[(dev|watch|session|PIPE|refresh|verify|post-run|warn|err|DB)\]/) { print raw; fflush(); next }
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

SESSION_PID=""
watch_nms_process_session >"$PIPE" 2>&1 &
SESSION_PID=$!

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
  [[ -n "${SESSION_PID:-}" ]] && kill "$SESSION_PID" 2>/dev/null || true
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
