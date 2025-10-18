#!/usr/bin/env bash

# === CONTRACT: scripts/import_latest.sh =======================================
# Purpose:
#   Import the most recent No Man's Sky save into MariaDB:
#     1) decode save*.hg → JSON (cached),
#     2) extract inventory CSVs (totals/slots),
#     3) upsert a row into nms_snapshots (with mtime + sha),
#     4) replace nms_items for that snapshot via LOAD DATA,
#     5) ensure the active save_root is set in nms_save_roots.
#
# Behavior & Invariants:
#   - Idempotent by fingerprint: if {HG mtime, JSON sha256} matches last DB row
#     for source_path and NMS_IMPORT_FORCE != "1", the script exits 0 without
#     re-importing.
#   - Uses the internal decoder only: scripts/python/pipeline/nms_hg_decoder.py.
#   - MariaDB CLI is invoked exactly as:
#       mariadb -u "$NMS_DB_USER" -p -D "$NMS_DB_NAME" -N -e "<SQL>"
#   - Assumes DB charset=utf8mb4 and collation=utf8mb4_unicode_ci are in effect.
#
# Exports (Bash functions in this file):
#   - dbq(sql)         : run SQL against MariaDB with -N; prints result.
#   - escape_sql(text) : escape single quotes for safe SQL literal usage.
#
# Environment (read):
#   - ENV_FILE          : path to .env (defaults to "$ROOT/.env" if unset).
#   - NMS_DB_USER (req) : MariaDB user.
#   - NMS_DB_NAME (req) : MariaDB database.
#   - NMS_SAVE_ROOT(req): logical save root name used by UI/views.
#   - NMS_PROFILE (req) : profile identifier used in file naming.
#   - NMS_CACHE_DIR(opt): cache for decoded JSON (default: $ROOT/.cache/decoded).
#   - NMS_HG_PATH  (opt): explicit path to a save*.hg; if absent, choose newest
#                         save*.hg in $NMS_SAVE_ROOT/$NMS_PROFILE directory.
#   - NMS_DECODER_DEBUG(opt: 0|1): pass --debug to decoder when =1.
#   - NMS_IMPORT_FORCE (opt: 0|1): when =1, bypass fingerprint short-circuit.
#
# External commands required:
#   bash(>=4), python3, mariadb (client), sha256sum, sed, awk, stat, date,
#   ls, head, mkdir, test/[, and standard coreutils.
#
# Files & Layout:
#   - Input  : latest save*.hg (optionally via $NMS_HG_PATH).
#   - Output : JSON cache at $NMS_CACHE_DIR; CSVs at $ROOT/storage/decoded.
#   - Python : scripts/python/pipeline/nms_hg_decoder.py
#              scripts/python/nms_extract_inventory.py
#
# SQL touch points / invariants:
#   - nms_snapshots(source_path, source_mtime, decoded_mtime, json_path,
#                   json_bytes, json_sha256, save_root, snapshot_id[PK]).
#   - nms_items(snapshot_id, inventory, container_id, slot_index,
#               resource_id, amount, item_type).
#   - nms_save_roots(save_root PK/UNIQUE, is_active).
#   - Items load path uses: DELETE … WHERE snapshot_id = ?; then LOAD DATA LOCAL
#     INFILE '<CSV>' INTO TABLE nms_items … with item_type derived as:
#     CASE WHEN LEFT(@resource_id,1)='^' THEN 'Substance' ELSE 'Product' END.
#
# Side effects:
#   - Writes/updates under $ROOT/.cache/decoded and $ROOT/storage/decoded.
#   - Inserts/updates rows in nms_snapshots, nms_items, nms_save_roots.
#   - Flips exactly one save_root to is_active=1; others set to 0.
#
# Exit codes:
#   0 = success (including "unchanged, skipped"),
#   2 = missing save*.hg,
#   other non-zero = failures from decoder, extractor, or SQL execution.
#
# Security notes:
#   - Uses mariadb -p (interactive password); does not echo credentials.
#   - escape_sql() guards single quotes in SQL literals.
#
# Compatibility:
#   - No function names or CLI flags changed. Paths and includes unchanged.
#
# EXTRA RULES (owner may append below):
#   - Do not replace the internal decoder with external tools.
#   - Preserve the exact MariaDB CLI shape and -N flag.
# ===============================================================================


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
