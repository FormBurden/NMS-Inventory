#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"
[[ -f "$ENV_FILE" ]] || { echo "Missing .env at $ENV_FILE"; exit 2; }

set -a; source "$ENV_FILE"; set +a
: "${NMS_DB_HOST:?}"; : "${NMS_DB_PORT:?}"; : "${NMS_DB_USER:?}"; : "${NMS_DB_PASS:?}"; : "${NMS_DB_NAME:?}"
: "${NMS_SAVE_ROOT:?}"; : "${NMS_PROFILE:?}"

CACHE="${NMS_CACHE_DIR:-$REPO_ROOT/.cache/decoded}"
OUTDIR="${NMS_OUT_DIR:-$REPO_ROOT/output}"
mkdir -p "$CACHE" "$OUTDIR"

# Choose the newest save*.hg (handles save.hg vs save2.hg)
HG_DIR="$NMS_SAVE_ROOT/$NMS_PROFILE"
HG=$(ls -1t "$HG_DIR"/save*.hg 2>/dev/null | head -n1 || true)
[[ -n "$HG" && -f "$HG" ]] || { echo "Missing save files in $HG_DIR (expected save*.hg)"; exit 2; }
HG_BASE="$(basename "$HG")"
JSON="$CACHE/${NMS_PROFILE}_${HG_BASE}.json"
SLOTS="$OUTDIR/${NMS_PROFILE}_slots.csv"
TOTALS="$OUTDIR/${NMS_PROFILE}_totals.csv"

dbq() { MYSQL_PWD="$NMS_DB_PASS" mariadb \
  -h "$NMS_DB_HOST" -P "$NMS_DB_PORT" \
  -u "$NMS_DB_USER" -D "$NMS_DB_NAME" -N -B -e "$1"; }


escape_sql() { printf "%s" "$1" | sed "s/'/''/g"; }

# Decode if JSON missing or stale
NEED_DECODE=0
if [[ ! -f "$JSON" ]]; then NEED_DECODE=1
elif [[ "$HG" -nt "$JSON" ]]; then NEED_DECODE=1
fi
DEC_FLAGS=$([ "${NMS_DECODER_DEBUG:-0}" = "1" ] && echo "--debug" || echo "")
if [[ $NEED_DECODE -eq 1 ]]; then
  python3 "$REPO_ROOT/scripts/python/pipeline/nms_hg_decoder.py" --in "$HG" --out "$JSON" --pretty $DEC_FLAGS
fi

# Fingerprint
HG_MTIME=$(date -d "@$(stat -c %Y "$HG")" '+%F %T')
JSON_MTIME=$(date -d "@$(stat -c %Y "$JSON")" '+%F %T')
JSON_SHA=$(sha256sum "$JSON" | awk '{print $1}')
HG_ESC=$(escape_sql "$HG")

# Skip if unchanged vs DB
read -r LAST_ID LAST_SRC LAST_SHA <<<"$(dbq "
  SELECT snapshot_id, source_mtime, json_sha256
  FROM nms_snapshots
  WHERE source_path='$HG_ESC'
  ORDER BY snapshot_id DESC
  LIMIT 1;")" || true

if [[ -n "${LAST_ID:-}" && "$LAST_SRC" == "$HG_MTIME" && "$LAST_SHA" == "$JSON_SHA" && "${NMS_IMPORT_FORCE:-0}" != "1" ]]; then
  echo "[import] unchanged (mtime+sha match DB); skipping extract/import."
  exit 0
fi

# Extract
python3 "$REPO_ROOT/scripts/python/nms_extract_inventory.py" \
  --json "$JSON" \
  --out-totals "$TOTALS" \
  --out-slots  "$SLOTS"

# UPSERT snapshot
dbq "INSERT INTO nms_snapshots
       (source_path, save_root, source_mtime, decoded_mtime, json_sha256)
     VALUES
       ('$HG_ESC', '$NMS_PROFILE', '$HG_MTIME', '$JSON_MTIME', '$JSON_SHA')
     ON DUPLICATE KEY UPDATE
       decoded_mtime = VALUES(decoded_mtime),
       json_sha256   = VALUES(json_sha256);"

# Deterministic snapshot id (works across connections)
SNAP=$(dbq "SELECT snapshot_id FROM nms_snapshots
            WHERE source_path='$HG_ESC' AND source_mtime='$HG_MTIME'
            ORDER BY snapshot_id DESC LIMIT 1;")
echo "[import] snapshot_id = ${SNAP:-?}"

# Replace rows for this snapshot, then load
dbq "DELETE FROM nms_items WHERE snapshot_id=${SNAP:-0};"

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

# --- ensure/activate save_root so UI views populate -----------------------
# 1) Seed nms_save_roots from distinct roots seen in snapshots (idempotent)
dbq "INSERT IGNORE INTO nms_save_roots(save_root,is_active)
     SELECT DISTINCT save_root, 0 FROM nms_snapshots;"

# 2) Choose the newest non-'decoded' root (fallback to NMS_PROFILE)
NEW_ROOT="$(dbq "SELECT save_root
                 FROM nms_snapshots
                 WHERE save_root <> 'decoded'
                 ORDER BY decoded_mtime DESC, source_mtime DESC, snapshot_id DESC
                 LIMIT 1;")"
if [[ -z "$NEW_ROOT" ]]; then NEW_ROOT="$NMS_PROFILE"; fi

# 3) Flip active flag to the chosen root (ensuring it exists)
dbq "UPDATE nms_save_roots SET is_active=0;"
dbq "INSERT IGNORE INTO nms_save_roots(save_root,is_active) VALUES ('$NEW_ROOT',0);"
dbq "UPDATE nms_save_roots SET is_active=1 WHERE save_root='$NEW_ROOT';"

# (tiny sanity print — helpful in logs)
dbq "SELECT save_root,is_active FROM nms_save_roots
     ORDER BY is_active DESC, save_root LIMIT 5;"
echo "[import] active save_root = ${NEW_ROOT}"

dbq "SOURCE db/migrations/20251017_0012_recent_sort_views.sql"

echo "[import] applied recent-sort views"

echo "[import] done."

