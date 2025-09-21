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
echo "[dev] preflight refresh (decode/import if needed)"

# Paths used for the fingerprint rule (matches your earlier working flow)
# SAVE2.hg is expected under $NMS_SAVE_ROOT/$NMS_PROFILE/
HG_SAVE2="${NMS_SAVE_ROOT:-}/$(basename "${NMS_PROFILE:-}")/save2.hg"
JSON_SAVE2="$REPO_ROOT/.cache/decoded/save2.json"
FP_FILE="$REPO_ROOT/.cache/decoded/.fingerprint"

need_decode=0
if [[ -n "${NMS_SAVE_ROOT:-}" && -n "${NMS_PROFILE:-}" && -f "$HG_SAVE2" ]]; then
  mkdir -p "$REPO_ROOT/.cache/decoded"
  if [[ ! -f "$JSON_SAVE2" ]]; then
    need_decode=1
  elif [[ "$HG_SAVE2" -nt "$JSON_SAVE2" ]]; then
    need_decode=1
  fi
else
  # If we cannot resolve the save path, we skip local decode decision and let importer handle it.
  need_decode=0
fi

# Compute current fingerprint if we have both files
cur_fp=""
if [[ -f "$HG_SAVE2" && -f "$JSON_SAVE2" ]]; then
  hg_mtime="$(date -d "@$(stat -c %Y "$HG_SAVE2")" '+%F %T')" || hg_mtime=""
  json_sha="$(sha256sum "$JSON_SAVE2" | awk '{print $1}')" || json_sha=""
  cur_fp="${hg_mtime}|${json_sha}"
fi

# Decide if importer should run
run_importer=0
if [[ $need_decode -eq 1 ]]; then
  run_importer=1
elif [[ -n "$cur_fp" && -f "$FP_FILE" ]]; then
  if [[ "$(<"$FP_FILE")" != "$cur_fp" ]]; then
    run_importer=1
  fi
fi

IMPORTER="$REPO_ROOT/scripts/python/nms_import_initial.py"
if [[ -f "$IMPORTER" && $run_importer -eq 1 ]]; then
  # Run importer (non-fatal). If NMS_DB_PASS is set, export to MYSQL_PWD for the pipeline.
  set +e
  if [[ -n "${NMS_DB_PASS:-}" ]]; then
    (
      export MYSQL_PWD="$NMS_DB_PASS"
      python3 "$IMPORTER" --decode \
        ${NMS_DECODER:+--decoder "$NMS_DECODER"} \
        ${NMS_SAVES_DIRS:+--saves-dirs "$NMS_SAVES_DIRS"} \
      | mariadb --local-infile=1 \
          -h "${NMS_DB_HOST:-localhost}" \
          -P "${NMS_DB_PORT:-3306}" \
          -u "${NMS_DB_USER:-root}" \
          -D "${NMS_DB_NAME:-nms_database}"
    ) >"$PIPE" 2>&1
    st=$?
  else
    python3 "$IMPORTER" --decode \
      ${NMS_DECODER:+--decoder "$NMS_DECODER"} \
      ${NMS_SAVES_DIRS:+--saves-dirs "$NMS_SAVES_DIRS"} \
    | mariadb --local-infile=1 \
        -h "${NMS_DB_HOST:-localhost}" \
        -P "${NMS_DB_PORT:-3306}" \
        -u "${NMS_DB_USER:-root}" \
        -D "${NMS_DB_NAME:-nms_database}" \
        -p
    st=$?
  fi
  set -e
  if [[ ${st:-0} -ne 0 ]]; then
    echo "[warn] Import failed (exit ${st}). Continuing to start server."
  else
    echo "[runtime] Done."
    # Refresh JSON + write fingerprint when available
    if [[ -f "$HG_SAVE2" && -f "$JSON_SAVE2" ]]; then
      hg_mtime="$(date -d "@$(stat -c %Y "$HG_SAVE2")" '+%F %T')" || true
      json_sha="$(sha256sum "$JSON_SAVE2" | awk '{print $1}')" || true
      echo "${hg_mtime}|${json_sha}" > "$FP_FILE"
    fi
  fi
else
  echo "[runtime] Import skipped (unchanged fingerprint or importer missing)"
fi

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
