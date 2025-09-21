#!/usr/bin/env bash
set -euo pipefail

# Repo root & .env
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"
[[ -f "$ENV_FILE" ]] || { echo "[err] Missing .env at $ENV_FILE"; exit 2; }

# Load .env
set -a; source "$ENV_FILE"; set +a
: "${NMS_DB_HOST:?}"; : "${NMS_DB_PORT:?}"; : "${NMS_DB_USER:?}"; : "${NMS_DB_PASS:?}"; : "${NMS_DB_NAME:?}"
: "${NMS_SAVE_ROOT:?}"; : "${NMS_PROFILE:?}"

# Paths
CACHE="${NMS_CACHE_DIR:-$REPO_ROOT/.cache/decoded}"
OUTDIR="${NMS_OUT_DIR:-$REPO_ROOT/output}"
mkdir -p "$CACHE" "$OUTDIR"

HG="$NMS_SAVE_ROOT/$NMS_PROFILE/save2.hg"
JSON="$CACHE/${NMS_PROFILE}_save2.hg.json"
SLOTS="$OUTDIR/${NMS_PROFILE}_slots.csv"
TOTALS="$OUTDIR/${NMS_PROFILE}_totals.csv"

dbq() { MYSQL_PWD="$NMS_DB_PASS" mariadb --local-infile=1 \
  -h "$NMS_DB_HOST" -P "$NMS_DB_PORT" -u "$NMS_DB_USER" -D "$NMS_DB_NAME" -N -B -e "$1"; }

echo "[dev] preflight refresh (decode/import if needed)"
echo "[runtime] Decoding latest saves → $CACHE"

[[ -f "$HG" ]] || { echo "[err] Missing save file: $HG"; exit 2; }

# Decode if JSON missing or older than HG
NEED_DECODE=0
if [[ ! -f "$JSON" ]]; then
  NEED_DECODE=1
else
  if [[ "$HG" -nt "$JSON" ]]; then NEED_DECODE=1; fi
fi

DEC_FLAGS=$([ "${NMS_DECODER_DEBUG:-0}" = "1" ] && echo "--debug" || echo "")
if [[ $NEED_DECODE -eq 1 ]]; then
  python3 "$REPO_ROOT/scripts/python/nms_hg_decoder.py" --in "$HG" --out "$JSON" --pretty $DEC_FLAGS
else
  echo "[runtime] JSON is fresh (skip decode)"
fi

echo "[runtime] Extracting inventory → $OUTDIR"
python3 "$REPO_ROOT/scripts/python/nms_extract_inventory.py" \
  --json "$JSON" \
  --out-totals "$TOTALS" \
  --out-slots  "$SLOTS"

echo "[runtime] Importing decoded manifest → MariaDB ($NMS_DB_NAME)"

# Build snapshot values
HG_MTIME=$(date -d "@$(stat -c %Y "$HG")" '+%F %T')
JSON_MTIME=$(date -d "@$(stat -c %Y "$JSON")" '+%F %T')
JSON_SHA=$(sha256sum "$JSON" | awk '{print $1}')

# UPSERT snapshot (idempotent for same source_path + source_mtime)
SQL_INS=$(cat <<SQL
INSERT INTO nms_snapshots
  (source_path, save_root, source_mtime, decoded_mtime, json_sha256)
VALUES
  ('$HG', '$NMS_PROFILE', '$HG_MTIME', '$JSON_MTIME', '$JSON_SHA')
ON DUPLICATE KEY UPDATE
  snapshot_id   = LAST_INSERT_ID(snapshot_id),
  decoded_mtime = VALUES(decoded_mtime),
  json_sha256   = VALUES(json_sha256);
SQL
)
echo "--------------"
echo "$SQL_INS"
echo "--------------"
dbq "$SQL_INS"

SNAP=$(dbq "SELECT LAST_INSERT_ID();")
echo "[dev] snapshot_id = $SNAP"

# Clear any previous rows for this snapshot (avoid UNIQUE conflicts)
dbq "DELETE FROM nms_items WHERE snapshot_id=$SNAP;"

# Load slots
dbq "LOAD DATA LOCAL INFILE '$(printf %q "$SLOTS")'
     INTO TABLE nms_items
     FIELDS TERMINATED BY ',' ENCLOSED BY '\"'
     IGNORE 1 LINES
     (@owner_type,@inventory,@container_id,@slot_index,@resource_id,@amount)
     SET snapshot_id=$SNAP,
         owner_type=@owner_type,
         inventory=@inventory,
         container_id=@container_id,
         slot_index=@slot_index,
         resource_id=@resource_id,
         amount=@amount,
         item_type=CASE WHEN LEFT(@resource_id,1)='^' THEN 'Substance' ELSE 'Product' END;"

# Quick stats
dbq "SELECT COUNT(*) AS rows_loaded FROM nms_items WHERE snapshot_id=$SNAP;"
echo "[dev] done."
