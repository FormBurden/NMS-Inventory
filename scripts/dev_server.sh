#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"
[[ -f "$ENV_FILE" ]] || { echo "[err] Missing .env at $ENV_FILE"; exit 2; }

# load env
set -a; source "$ENV_FILE"; set +a
: "${NMS_DB_HOST:?}"; : "${NMS_DB_PORT:?}"; : "${NMS_DB_USER:?}"; : "${NMS_DB_PASS:?}"; : "${NMS_DB_NAME:?}"
: "${NMS_SAVE_ROOT:?}"; : "${NMS_PROFILE:?}"

CACHE="${NMS_CACHE_DIR:-$REPO_ROOT/.cache/decoded}"
OUTDIR="${NMS_OUT_DIR:-$REPO_ROOT/output}"
mkdir -p "$CACHE" "$OUTDIR"

HG="$NMS_SAVE_ROOT/$NMS_PROFILE/save2.hg"
JSON="$CACHE/${NMS_PROFILE}_save2.hg.json"
SLOTS="$OUTDIR/${NMS_PROFILE}_slots.csv"
TOTALS="$OUTDIR/${NMS_PROFILE}_totals.csv"
FP="$CACHE/${NMS_PROFILE}.fingerprint"   # local skip token

dbq() { MYSQL_PWD="$NMS_DB_PASS" mariadb --ssl-mode=DISABLED --local-infile=1 \
  -h "$NMS_DB_HOST" -P "$NMS_DB_PORT" -u "$NMS_DB_USER" -D "$NMS_DB_NAME" -N -B -e "$1"; }
escape_sql() { printf "%s" "$1" | sed "s/'/''/g"; }

preflight_refresh() {
  echo "[dev] preflight refresh (decode/import if needed)"
  echo "[runtime] Decoding latest saves → $CACHE"
  [[ -f "$HG" ]] || { echo "[err] Missing save file: $HG"; exit 2; }

  # Decode only if JSON missing or older than HG
  NEED_DECODE=0
  if [[ ! -f "$JSON" ]]; then NEED_DECODE=1
  elif [[ "$HG" -nt "$JSON" ]]; then NEED_DECODE=1
  fi
  DEC_FLAGS=$([ "${NMS_DECODER_DEBUG:-0}" = "1" ] && echo "--debug" || echo "")
  if [[ $NEED_DECODE -eq 1 ]]; then
    python3 "$REPO_ROOT/scripts/python/nms_hg_decoder.py" --in "$HG" --out "$JSON" --pretty $DEC_FLAGS
  else
    echo "[runtime] JSON is fresh (skip decode)"
  fi

  # --- Fingerprint (before extraction/import) ---
  HG_MTIME=$(date -d "@$(stat -c %Y "$HG")" '+%F %T')
  JSON_MTIME=$(date -d "@$(stat -c %Y "$JSON")" '+%F %T')
  JSON_SHA=$(sha256sum "$JSON" | awk '{print $1}')
  CUR_FP="$HG_MTIME|$JSON_SHA"
  HG_ESC=$(escape_sql "$HG")

  # 1) Skip via local fingerprint file
  if [[ -f "$FP" ]]; then
    PREV_FP="$(<"$FP")"
    if [[ "$PREV_FP" == "$CUR_FP" ]]; then
      echo "[preflight] unchanged (local fingerprint): $CUR_FP"
      return 0
    fi
  fi

  # 2) Skip via DB snapshot (exact path+mtime+sha match)
  DB_SHA="$(dbq "SELECT json_sha256 FROM nms_snapshots
                 WHERE source_path='$HG_ESC' AND source_mtime='$HG_MTIME'
                 ORDER BY snapshot_id DESC LIMIT 1;" 2>/dev/null || true)"
  if [[ -n "$DB_SHA" && "$DB_SHA" == "$JSON_SHA" ]]; then
    echo "[preflight] unchanged (DB fingerprint): $HG_MTIME | $JSON_SHA"
    printf '%s\n' "$CUR_FP" > "$FP"
    return 0
  fi

  # --- Changed → extract and import ---
  echo "[runtime] Extracting inventory → $OUTDIR"
  python3 "$REPO_ROOT/scripts/python/nms_extract_inventory.py" \
    --json "$JSON" \
    --out-totals "$TOTALS" \
    --out-slots  "$SLOTS"

  echo "[runtime] Importing decoded manifest → MariaDB ($NMS_DB_NAME)"
  SQL_INS=$(cat <<SQL
INSERT INTO nms_snapshots
  (source_path, save_root, source_mtime, decoded_mtime, json_sha256)
VALUES
  ('$HG_ESC', '$NMS_PROFILE', '$HG_MTIME', '$JSON_MTIME', '$JSON_SHA')
ON DUPLICATE KEY UPDATE
  decoded_mtime = VALUES(decoded_mtime),
  json_sha256   = VALUES(json_sha256);
SQL
)
  echo "--------------"; echo "$SQL_INS"; echo "--------------"
  dbq "$SQL_INS"

  SNAP="$(dbq "SELECT snapshot_id FROM nms_snapshots
               WHERE source_path='$HG_ESC' AND source_mtime='$HG_MTIME'
               ORDER BY snapshot_id DESC LIMIT 1;")"
  echo "[dev] snapshot_id = ${SNAP:-?}"

  # Replace rows for this snapshot to avoid dups
  dbq "DELETE FROM nms_items WHERE snapshot_id=${SNAP:-0};"

  # Load slots
  dbq "LOAD DATA LOCAL INFILE '$(printf %q "$SLOTS")'
       INTO TABLE nms_items
       FIELDS TERMINATED BY ',' ENCLOSED BY '\"'
       IGNORE 1 LINES
       (@owner_type,@inventory,@container_id,@slot_index,@resource_id,@amount)
       SET snapshot_id=${SNAP:-0},
           owner_type=@owner_type,
           inventory=@inventory,
           container_id=@container_id,
           slot_index=@slot_index,
           resource_id=@resource_id,
           amount=@amount,
           item_type=CASE WHEN LEFT(@resource_id,1)='^' THEN 'Substance' ELSE 'Product' END;"

  dbq "SELECT COUNT(*) AS rows_loaded FROM nms_items WHERE snapshot_id=${SNAP:-0};"

  # Write/refresh local fingerprint
  printf '%s\n' "$CUR_FP" > "$FP"
}

# Run preflight once (will print [preflight] unchanged if it skips)
preflight_refresh
echo "[dev] preflight done."

# Start watcher (background) if available
WATCH_PID=""
if command -v inotifywait >/dev/null 2>&1; then
  echo "[dev] starting save watcher (scripts/watch_saves.sh)"
  bash "$REPO_ROOT/scripts/watch_saves.sh" &
  WATCH_PID=$!
  echo "[dev] watcher pid = $WATCH_PID"
else
  echo "[dev] inotifywait not found; install 'inotify-tools' to enable live importing."
fi

# Start dev server and keep running
HOST="${NMS_DEV_HOST:-127.0.0.1}"
PORT="${NMS_DEV_PORT:-8787}"
if [[ -n "${NMS_DEV_ROOT:-}" ]]; then
  ROOT="$NMS_DEV_ROOT"
else
  [[ -d "$REPO_ROOT/public" ]] && ROOT="$REPO_ROOT/public" || ROOT="$REPO_ROOT"
fi

echo "[dev] starting server on http://${HOST}:${PORT}"
echo "[dev] serving root: $ROOT"

trap 'echo; echo "[dev] shutting down..."; [[ -n "$WATCH_PID" ]] && kill "$WATCH_PID" 2>/dev/null || true; [[ -n "$SERVER_PID" ]] && kill "$SERVER_PID" 2>/dev/null || true; wait; exit 0' INT TERM

if [[ -n "${NMS_DEV_CMD:-}" ]]; then
  ( cd "$ROOT" && eval "$NMS_DEV_CMD" ) &
  SERVER_PID=$!
else
  ( cd "$ROOT" && python3 -m http.server "$PORT" --bind "$HOST" ) &
  SERVER_PID=$!
fi

echo "[dev] server pid = $SERVER_PID"
echo "[dev] ready. Press Ctrl-C to stop."
wait "$SERVER_PID"
