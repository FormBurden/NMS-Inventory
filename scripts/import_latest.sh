#!/usr/bin/env bash

set -Eeuo pipefail

# Import the latest NMS save into the database:
#  - decode save*.hg -> JSON (cached)
#  - extract slots/totals via Python helper
#  - upsert snapshot metadata
#  - replace nms_items for that snapshot and load from CSV
#  - ensure the active save_root is set

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
[[ -f "$ENV_FILE" ]] || { echo "[import] Missing .env at $ENV_FILE"; exit 2; }

set -a; source "$ENV_FILE"; set +a
: "${NMS_DB_USER:?}"
: "${NMS_DB_NAME:?}"
: "${NMS_SAVE_ROOT:?}"
: "${NMS_PROFILE:?}"

CACHE="${NMS_CACHE_DIR:-$ROOT/.cache/decoded}"
OUTDIR="$ROOT/storage/decoded"
mkdir -p "$CACHE" "$OUTDIR"

# Resolve latest HG path (prefer explicit NMS_HG_PATH if file; else newest in profile dir)
if [[ -n "${NMS_HG_PATH:-}" && -f "$NMS_HG_PATH" ]]; then
  HG="$NMS_HG_PATH"
else
  HG_DIR="${NMS_SAVE_ROOT%/}/${NMS_PROFILE}"
  HG="$(ls -1t "$HG_DIR"/save*.hg 2>/dev/null | head -n1 || true)"
fi
[[ -n "$HG" && -f "$HG" ]] || { echo "[import] Missing save files (save*.hg)"; exit 2; }

HG_BASE="$(basename "$HG")"
JSON="$CACHE/${NMS_PROFILE}_${HG_BASE}.json"
SLOTS="$OUTDIR/${NMS_PROFILE}_slots.csv"
TOTALS="$OUTDIR/${NMS_PROFILE}_totals.csv"

# MariaDB helper (preferred CLI shape; -N to suppress headers)
dbq() { mariadb -u "$NMS_DB_USER" -p -D "$NMS_DB_NAME" -N -e "$1"; }

escape_sql() { sed "s/'/''/g" <<<"$1"; }

# Decode if needed
NEED_DECODE=0
if [[ ! -f "$JSON" ]]; then NEED_DECODE=1
elif [[ "$HG" -nt "$JSON" ]]; then NEED_DECODE=1
fi
DEC_FLAGS=$([ "${NMS_DECODER_DEBUG:-0}" = "1" ] && echo "--debug" || echo "")
if [[ $NEED_DECODE -eq 1 ]]; then
  echo "[import] decoding -> $JSON"
  python3 "$ROOT/scripts/python/pipeline/nms_hg_decoder.py" --in "$HG" --out "$JSON" --pretty $DEC_FLAGS
fi

# Fingerprint and short-circuit if unchanged
HG_MTIME=$(date -d "@$(stat -c %Y "$HG")" '+%F %T')
JSON_MTIME=$(date -d "@$(stat -c %Y "$JSON")" '+%F %T')
JSON_SHA=$(sha256sum "$JSON" | awk '{print $1}')
HG_ESC=$(escape_sql "$HG")

read -r LAST_ID LAST_SRC LAST_SHA < <(dbq "
  SELECT snapshot_id, source_mtime, json_sha256
  FROM nms_snapshots
  WHERE source_path='$HG_ESC'
  ORDER BY snapshot_id DESC
  LIMIT 1;")

if [[ -n "${LAST_ID:-}" && "$LAST_SRC" == "$HG_MTIME" && "$LAST_SHA" == "$JSON_SHA" && "${NMS_IMPORT_FORCE:-0}" != "1" ]]; then
  echo "[import] unchanged (mtime+sha match DB); skipping extract/import."
  exit 0
fi

# Extract CSVs
python3 "$ROOT/scripts/python/nms_extract_inventory.py" \
  --json "$JSON" \
  --out-totals "$TOTALS" \
  --out-slots  "$SLOTS"

# UPSERT snapshot
dbq "INSERT INTO nms_snapshots
       (source_path, save_root, source_mtime, decoded_mtime, json_sha256)
     VALUES
       ('$HG_ESC', '$NMS_PROFILE', '$HG_MTIME', '$JSON_MTIME', '$JSON_SHA')
     ON DUPLICATE KEY UPDATE
       save_root=VALUES(save_root),
       source_mtime=VALUES(source_mtime),
       decoded_mtime=VALUES(decoded_mtime),
       json_sha256=VALUES(json_sha256)"

SNAP="$(dbq "SELECT snapshot_id FROM nms_snapshots WHERE source_path='$HG_ESC' ORDER BY snapshot_id DESC LIMIT 1;")"
[[ -n "$SNAP" ]] || { echo "[import][ERR] failed to resolve snapshot_id"; exit 1; }
echo "[import] snapshot_id = ${SNAP}"

# Replace rows for this snapshot, then LOAD DATA from CSV
dbq "DELETE FROM nms_items WHERE snapshot_id=${SNAP:-0};"

# Note: require LOCAL INFILE to be enabled client-side; MariaDB CLI supports it by default.
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

# Ensure/activate save_root so UI views populate
dbq "INSERT IGNORE INTO nms_save_roots(save_root,is_active)
     SELECT DISTINCT save_root, 0 FROM nms_snapshots;"

NEW_ROOT="$(dbq "SELECT save_root
                 FROM nms_snapshots
                 WHERE save_root <> 'decoded'
                 ORDER BY decoded_mtime DESC, source_mtime DESC, snapshot_id DESC
                 LIMIT 1;")"
[[ -z "$NEW_ROOT" ]] && NEW_ROOT="$NMS_PROFILE"

dbq "UPDATE nms_save_roots SET is_active=0;"
dbq "INSERT IGNORE INTO nms_save_roots(save_root,is_active) VALUES ('$NEW_ROOT',0);"
dbq "UPDATE nms_save_roots SET is_active=1 WHERE save_root='$NEW_ROOT';"

echo "[import] active save_root = ${NEW_ROOT}"
echo "[import] done."
