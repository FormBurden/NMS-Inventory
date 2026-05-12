#!/usr/bin/env bash

# NMS-Inventory — decode → clean → fullparse → manifest → initial import → ledger
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"

[[ -f "$ENV_FILE" ]] || { echo "[PIPE][ERROR] Missing .env at $ENV_FILE"; exit 2; }

# --- helpers -----------------------------------------------------------------
get_env() { # get_env VAR [default]
  local k="$1" d="${2:-}" v=""
  if [[ -n "${!k-}" ]]; then
    v="${!k}"
  else
    v="$(grep -E "^[[:space:]]*${k}=" "$ENV_FILE" | tail -n1 | sed -E "s/^[^=]+=//" | sed -E 's/^"(.*)"$/\1/')"
  fi
  [[ -n "$v" ]] && { printf '%s' "$v"; return 0; }
  printf '%s' "$d"
}
strip_quotes(){ sed -E 's/^"(.*)"$/\1/' <<<"$1"; }

DEC="$ROOT/storage/decoded"
CLEAN="$ROOT/storage/cleaned"
LOGS="$ROOT/storage/logs"
mkdir -p "$DEC" "$CLEAN" "$LOGS"

# --- resolve config safely (avoid set -u trips) ------------------------------
SAVE_ROOT="$(strip_quotes "$(get_env NMS_SAVE_ROOT "")")"
PROFILE="$(strip_quotes "$(get_env NMS_PROFILE   "")")"
HG_HINT="$(strip_quotes "$(get_env NMS_HG_PATH   "")")"

# --- DB password reuse (no extra prompts if set) ------------------------------
DB_USER="$(strip_quotes "$(get_env NMS_DB_USER "")")"
DB_NAME="$(strip_quotes "$(get_env NMS_DB_NAME "")")"
DB_PASS="${DB_PASS:-$(strip_quotes "$(get_env NMS_DB_PASS "")")}"

maria() {
  # Keep required shape; include password inline only if present to avoid re-prompt.
  if [[ -n "$DB_PASS" ]]; then
    mariadb -u "$DB_USER" -p"$DB_PASS" "$@"
  else
    mariadb -u "$DB_USER" -p "$@"
  fi
}

cleanup_database_retention() {
  local retention
  local ledger_table
  local have_ledger

  retention="$(strip_quotes "$(get_env NMS_SNAPSHOT_RETENTION "25")")"
  ledger_table="$(strip_quotes "$(get_env NMS_DB_LEDGER_TABLE "nms_ledger_deltas")")"

  if [[ ! "$retention" =~ ^[0-9]+$ || "$retention" -lt 2 ]]; then
    retention=25
  fi

  if [[ ! "$ledger_table" =~ ^[A-Za-z0-9_]+$ ]]; then
    echo "[cleanup][WARN] Unsafe ledger table name; skipping DB retention cleanup."
    return 0
  fi

  have_ledger="$(maria -D "$DB_NAME" -N -e "SHOW TABLES LIKE '$ledger_table';" 2>/dev/null || true)"

  if [[ -n "$have_ledger" ]]; then
    if ! maria -D "$DB_NAME" -N -e "
DELETE d
  FROM \`$ledger_table\` d
  LEFT JOIN (
        SELECT snapshot_id
          FROM (
                SELECT snapshot_id
                  FROM nms_snapshots
              ORDER BY imported_at DESC, snapshot_id DESC
                 LIMIT $retention
               ) kept_from_inner
       ) kept_from
    ON kept_from.snapshot_id = d.from_snapshot_id
  LEFT JOIN (
        SELECT snapshot_id
          FROM (
                SELECT snapshot_id
                  FROM nms_snapshots
              ORDER BY imported_at DESC, snapshot_id DESC
                 LIMIT $retention
               ) kept_to_inner
       ) kept_to
    ON kept_to.snapshot_id = d.to_snapshot_id
 WHERE kept_from.snapshot_id IS NULL
    OR kept_to.snapshot_id IS NULL;
" >"$LOGS/cleanup_ledger_retention.$stamp.log" 2>&1; then
      echo "[cleanup][WARN] Ledger retention cleanup failed; see $LOGS/cleanup_ledger_retention.$stamp.log"
    fi
  fi

  if ! maria -D "$DB_NAME" -N -e "
DELETE s
  FROM nms_snapshots s
  LEFT JOIN (
        SELECT snapshot_id
          FROM (
                SELECT snapshot_id
                  FROM nms_snapshots
              ORDER BY imported_at DESC, snapshot_id DESC
                 LIMIT $retention
               ) kept_inner
       ) kept
    ON kept.snapshot_id = s.snapshot_id
 WHERE kept.snapshot_id IS NULL;
" >"$LOGS/cleanup_snapshot_retention.$stamp.log" 2>&1; then
    echo "[cleanup][WARN] Snapshot retention cleanup failed; see $LOGS/cleanup_snapshot_retention.$stamp.log"
    return 0
  fi

  maria -D "$DB_NAME" -N -e "SELECT 'snapshots_retained' AS tag, COUNT(*) FROM nms_snapshots;" || true
}

# --- choose save*.hg file -----------------------------------------------------
HG_FILE=""
if [[ -n "$HG_HINT" && -f "$HG_HINT" ]]; then
  HG_FILE="$HG_HINT"
else
  HG_DIR=""
  if [[ -n "$HG_HINT" && -d "$HG_HINT" ]]; then
    HG_DIR="${HG_HINT%/}"
  elif [[ -n "$SAVE_ROOT" && -n "$PROFILE" && -d "${SAVE_ROOT%/}/${PROFILE}" ]]; then
    HG_DIR="${SAVE_ROOT%/}/${PROFILE}"
  fi
  if [[ -n "$HG_DIR" ]]; then
    HG_FILE="$(ls -1t "$HG_DIR"/save*.hg 2>/dev/null | head -n1 || true)"
  fi
fi

if [[ -z "$HG_FILE" || ! -f "$HG_FILE" ]]; then
  echo "[PIPE][ERROR] No save*.hg found."
  echo "  Tried:"
  echo "    NMS_HG_PATH file: ${HG_HINT:-<unset>}"
  echo "    Derived dir: ${SAVE_ROOT:+$SAVE_ROOT/}${PROFILE:-<no-profile>}"
  exit 2
fi

# --- outputs -----------------------------------------------------------------
stamp="$(date -u +%Y-%m-%d_%H-%M-%S)"
base="$(basename "$HG_FILE")"
case "$base" in
  save2.hg) out_name="save2.json" ;;
  save.hg)  out_name="save.json"  ;;
  *)        out_name="save_${stamp}.json" ;;
esac
raw_json="$DEC/$out_name"
clean_json="$CLEAN/${out_name%.json}.clean.json"

echo "[PIPE] using python: $(command -v python3 || command -v python)"
echo "[PIPE] decoding <- $HG_FILE"
echo "[PIPE] decoding -> $raw_json"
python3 "$ROOT/scripts/python/pipeline/nms_hg_decoder.py" --in "$HG_FILE" --out "$raw_json" --pretty ${NMS_DECODER_DEBUG:+--debug}

echo "[PIPE] cleaning -> $clean_json"
python3 "$ROOT/scripts/python/pipeline/nms_decode_clean.py" \
  --json "$raw_json" --out "$clean_json" --overwrite \
  >"$LOGS/nms_decode_clean.$stamp.log" 2>&1

# --- FULLPARSE (required to produce importable rows) --------------------------
# This script generates the fully parsed inventory artifacts used by the importer.
# It reads the latest cleaned JSON and writes into the project’s fullparse outputs.
echo "[PIPE] fullparse -> scripts/fullparse_present.sh"
bash "$ROOT/scripts/fullparse_present.sh" >"$LOGS/fullparse_present.$stamp.log" 2>&1

# --- manifest (rebuild after fullparse so importer sees fresh paths) ----------
SRC_MTIME="$(stat -c %Y "$HG_FILE" 2>/dev/null || stat -f %m "$HG_FILE" 2>/dev/null || echo "")"
python3 "$ROOT/scripts/python/pipeline/build_manifest.py" \
  --source "$HG_FILE" \
  --source-mtime "$SRC_MTIME" \

# --- initial import (generate SQL then execute via MariaDB) -------------------
run_initial_import() {
  local tmp_sql="$LOGS/initial_import.$stamp.sql"
  # Generate SQL from the latest manifest (will reference fullparse outputs)
  if ! python3 -m scripts.python.pipeline.ledger.cli_main initial_import \
      --db-name "$DB_NAME" \
      --manifest "$ROOT/storage/decoded/_manifest_recent.json" \
      --include-tech \
      >"$tmp_sql" 2>"$LOGS/initial_import.$stamp.log.py"; then
    echo "[PIPE][ERROR] db_import_initial.py failed; see $LOGS/initial_import.$stamp.log.py"
    return 1
  fi

  # Guard: abort if the generator produced the 'no snapshot rows' sentinel OR empty/valueless SQL
  if grep -q "no snapshot rows generated" "$tmp_sql"; then
    echo "[PIPE][ERROR] Import SQL contains no rows (fullparse likely missing or empty)."
    echo "  See: $LOGS/fullparse_present.$stamp.log and $LOGS/initial_import.$stamp.log.py"
    return 1
  fi
  # Also guard against an empty file
  if [ ! -s "$tmp_sql" ]; then
    echo "[PIPE][ERROR] Import SQL file is empty."
    echo "  See: $LOGS/fullparse_present.$stamp.log and $LOGS/initial_import.$stamp.log.py"
    return 1
  fi
  # And guard against a file with no VALUES rows
  if ! grep -Eiq 'INSERT[[:space:]]+INTO[[:space:]]+nms_items' "$tmp_sql"; then
    echo "[PIPE][ERROR] Import SQL has no nms_items inserts."
    echo "  See: $LOGS/fullparse_present.$stamp.log and $LOGS/initial_import.$stamp.log.py"
    return 1
  fi


  # Execute the SQL with preferred shape; reuse DB_PASS if present (no extra prompt)
  if ! maria -D "$DB_NAME" -N -e "$(cat "$tmp_sql")" \
        >"$LOGS/initial_import.$stamp.log" 2>&1; then
    echo "[PIPE][ERROR] MariaDB import failed; see $LOGS/initial_import.$stamp.log"
    return 1
  fi

  # Quick count to confirm rows landed
  maria -D "$DB_NAME" -N -e "SELECT 'rows_loaded' AS tag, COUNT(*) FROM nms_items WHERE snapshot_id=(SELECT MAX(snapshot_id) FROM nms_snapshots);" || true
}

run_initial_import

active_root_sql="${DEC//\\/\\\\}"
active_root_sql="${active_root_sql//\'/\\\'}"
if ! maria -D "$DB_NAME" -N -e "
ALTER TABLE nms_save_roots
  MODIFY save_root VARCHAR(512) NOT NULL;

INSERT INTO nms_save_roots(save_root, is_active)
VALUES ('$active_root_sql', 1)
ON DUPLICATE KEY UPDATE is_active = 1;
" >"$LOGS/activate_save_root.$stamp.log" 2>&1; then
  echo "[PIPE][WARN] Failed to activate save root; see $LOGS/activate_save_root.$stamp.log"
fi

# --- ledger -------------------------------------------------------------------
INITIAL_TABLE="$(get_env NMS_DB_INITIAL_TABLE "nms_initial_items")"
LEDGER_TABLE="$(get_env NMS_DB_LEDGER_TABLE  "nms_ledger_deltas")"
SESSION_MINUTES="$(get_env NMS_SESSION_MINUTES "120")"
USE_MTIME="$(get_env NMS_LEDGER_USE_MTIME "")"

echo "[PIPE] ledger compare -> $LEDGER_TABLE"
ledger_log="$LOGS/ledger.$stamp.log"

if grep -Eq '^[[:space:]]*pass[[:space:]]*(#.*)?$' "$ROOT/scripts/python/pipeline/ledger/cli_run.py"; then
  echo "[PIPE][WARN] ledger compare skipped; ledger/cli_run.py currently contains a placeholder run_ledger()."
  echo "[PIPE][WARN] inventory import completed successfully; ledger deltas require restoring the legacy run_ledger body."
else
  if ! PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" python3 "$ROOT/scripts/python/pipeline/nms_resource_ledger_v3.py" \
    --saves "$clean_json" \
    --baseline-db-table "$INITIAL_TABLE" \
    --baseline-snapshot latest \
    --db-write-ledger --db-env "$ENV_FILE" --db-ledger-table "$LEDGER_TABLE" \
    --session-minutes "$SESSION_MINUTES" \
    ${USE_MTIME:+--use-mtime} \
    >"$ledger_log" 2>&1; then
    echo "[PIPE][WARN] ledger compare failed; continuing after import."
    echo "[PIPE][WARN] ledger log: $ledger_log"
    tail -n 80 "$ledger_log" || true
  else
    tail -n 20 "$ledger_log" | sed 's/^/[PIPE] /'
  fi
fi

cleanup_database_retention

echo "[PIPE] done."

# --- Post-run: dump live schema snapshot (keeps db/_schema_dump/* fresh) ---
if [[ -x scripts/db_dump_schema.sh ]]; then
  echo "[post-run] dumping schema snapshot …"
  scripts/db_dump_schema.sh || echo "[warn] schema dump failed"
fi

