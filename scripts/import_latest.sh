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

HG="$NMS_SAVE_ROOT/$NMS_PROFILE/save2.hg"
[[ -f "$HG" ]] || { echo "Missing save: $HG"; exit 2; }

JSON="$CACHE/${NMS_PROFILE}_save2.hg.json"

dbq() { MYSQL_PWD="$NMS_DB_PASS" mariadb --local-infile=1 \
      -h "$NMS_DB_HOST" -P "$NMS_DB_PORT" \
      -u "$NMS_DB_USER" -D "$NMS_DB_NAME" -N -B -e "$1"; }

# 1) Decode
DEC_FLAGS=$([ "${NMS_DECODER_DEBUG:-0}" = "1" ] && echo "--debug" || echo "")
python3 "$REPO_ROOT/scripts/python/nms_hg_decoder.py" --in "$HG" --out "$JSON" --pretty $DEC_FLAGS

# 2) Extract inventory
python3 "$REPO_ROOT/scripts/python/nms_extract_inventory.py" \
  --json "$JSON" \
  --out-totals "$OUTDIR/${NMS_PROFILE}_totals.csv" \
  --out-slots  "$OUTDIR/${NMS_PROFILE}_slots.csv"

# 3) Snapshot UPSERT (matches the dev_server insert)
HG_MTIME=$(date -d "@$(stat -c %Y "$HG")" '+%F %T')
JSON_MTIME=$(date -d "@$(stat -c %Y "$JSON")" '+%F %T')
JSON_SHA=$(sha256sum "$JSON" | awk '{print $1}')

dbq "INSERT INTO nms_snapshots (source_path, save_root, source_mtime, decoded_mtime, json_sha256)
     VALUES ('${HG}', '${NMS_PROFILE}', '${HG_MTIME}', '${JSON_MTIME}', '${JSON_SHA}')
     ON DUPLICATE KEY UPDATE
       snapshot_id = LAST_INSERT_ID(snapshot_id),
       decoded_mtime = VALUES(decoded_mtime),
       json_sha256   = VALUES(json_sha256);"

SNAP=$(dbq "SELECT LAST_INSERT_ID();")
echo "Snapshot id: $SNAP"

# 4) Load slots
CSV="$OUTDIR/${NMS_PROFILE}_slots.csv"
dbq "LOAD DATA LOCAL INFILE '$(printf %q "$CSV")'
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

# 5) Sanity
dbq "SELECT COUNT(*) AS rows_loaded FROM nms_items WHERE snapshot_id=$SNAP;"
