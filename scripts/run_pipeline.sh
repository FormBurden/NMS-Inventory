#!/usr/bin/env bash

# =============================================================================
# CONTRACT: scripts/run_pipeline.sh
# Purpose
#   Orchestrate the No Man’s Sky inventory pipeline:
#   decode (*.hg) → clean → build manifest → initial DB import → ledger compare.
#   This CONTRACT documents invariants, dependencies, and side effects. Behavior
#   is unchanged; this is non-executable documentation plus guard rails.
#
# Invariants (must always hold)
#   - Bash safety flags enabled: set -Eeuo pipefail (already present).
#   - Uses MariaDB CLI via wrapper function `maria()` which MUST call:
#       mariadb -u "$DB_USER" -p ... -D "$DB_NAME" -N -e "<SQL>"
#     (password is only inlined when $DB_PASS is non-empty to avoid re-prompts).
#   - .env file exists and is readable at $ENV_FILE (defaults to "$ROOT/.env").
#   - Outputs remain under storage/* (decoded/cleaned/logs), not elsewhere.
#   - Ledger compares do not mutate initial table; they write only to ledger table.
#
# Inputs
#   - Environment (.env or exported):
#       NMS_SAVE_ROOT, NMS_PROFILE, NMS_HG_PATH,
#       NMS_DB_USER, NMS_DB_NAME, NMS_DB_PASS (optional),
#       NMS_DB_INITIAL_TABLE, NMS_DB_LEDGER_TABLE,
#       NMS_SESSION_MINUTES, NMS_LEDGER_USE_MTIME, NMS_DECODER_DEBUG.
#   - File system:
#       save file (save.hg or save2.hg) discoverable via NMS_HG_PATH or
#       $NMS_SAVE_ROOT/$NMS_PROFILE/.
#
# Requires / External commands & files
#   - Commands: python3, mariadb, grep, sed, tail, ls, head, date, basename, mkdir, cat, printf, echo.
#   - Python entrypoints:
#       scripts/python/pipeline/nms_hg_decoder.py
#       scripts/python/pipeline/nms_decode_clean.py
#       scripts/fullparse_present.sh
#       scripts/python/pipeline/build_manifest.py
#       scripts/python/db_import_initial.py
#       scripts/python/pipeline/nms_resource_ledger_v3.py
#
# Side Effects
#   - Creates/updates:
#       storage/decoded/*.json, storage/decoded/_manifest_recent.json
#       storage/cleaned/*.clean.json, storage/logs/*.log, *.sql (temp in logs).
#   - Database writes:
#       INSERTs into ${NMS_DB_INITIAL_TABLE:-nms_initial_items}
#       INSERT/UPDATEs into ${NMS_DB_LEDGER_TABLE:-nms_ledger_deltas}
#     (via `maria` and python ledger with --db-write-ledger).
#
# Charset / Collation Expectations
#   - Database uses utf8mb4 / utf8mb4_unicode_ci (as per migrations).
#
# Exports (symbols)
#   - Functions: get_env(VAR,[default]), strip_quotes(TEXT), maria(...), run_initial_import().
#   - CLI/Main: executing this script runs the full pipeline; no flags are added here.
#
# Logging
#   - All stages write timestamped logs under storage/logs/.
#
# Idempotency & Failure Modes
#   - If no save*.hg found → exit 2 (no DB mutations).
#   - If initial SQL generator yields “no snapshot rows generated” → abort import.
#   - Any failed mariadb/python step logs to storage/logs and returns non-zero.
#
# Compatibility / Touchpoints
#   - Do not rename functions above; callers may source or grep checks.
#   - Keep wrapper `maria()` semantics and argument pass-through stable.
#
# Contract Artifacts (mirrored tree layout)
#   - Symbol Manifest JSON:
#       contracts/symbols/scripts/run_pipeline.sh.json
#   - Checker:
#       scripts/contracts/checks/scripts/run_pipeline.sh.check.sh
#
# EXTRA RULES (owner may append below)
#   - (Append non-negotiable project rules here; keep ≤120 lines total.)
# =============================================================================


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
  --decoded "$raw_json" \
  --out "$ROOT/storage/decoded/_manifest_recent.json"

# --- initial import (generate SQL then execute via MariaDB) -------------------
run_initial_import() {
  local tmp_sql="$LOGS/initial_import.$stamp.sql"
  # Generate SQL from the latest manifest (will reference fullparse outputs)
  if ! python3 "$ROOT/scripts/python/db_import_initial.py" \
         --manifest "$ROOT/storage/decoded/_manifest_recent.json" \
         > "$tmp_sql" 2>"$LOGS/initial_import.$stamp.log.py"; then
    echo "[PIPE][ERROR] db_import_initial.py failed; see $LOGS/initial_import.$stamp.log.py"
    return 1
  fi

  # Guard: abort if the generator produced the 'no snapshot rows' sentinel
  if grep -q "no snapshot rows generated" "$tmp_sql"; then
    echo "[PIPE][ERROR] Import SQL contains no rows (fullparse likely missing or empty)."
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
  maria -D "$DB_NAME" -N -e "SELECT 'rows_loaded', COUNT(*) FROM nms_items WHERE snapshot_id=(SELECT MAX(snapshot_id) FROM nms_snapshots);" || true
}

run_initial_import

# --- ledger -------------------------------------------------------------------
INITIAL_TABLE="$(get_env NMS_DB_INITIAL_TABLE "nms_initial_items")"
LEDGER_TABLE="$(get_env NMS_DB_LEDGER_TABLE  "nms_ledger_deltas")"
SESSION_MINUTES="$(get_env NMS_SESSION_MINUTES "120")"
USE_MTIME="$(get_env NMS_LEDGER_USE_MTIME "")"

echo "[PIPE] ledger compare -> $LEDGER_TABLE"
python3 "$ROOT/scripts/python/pipeline/nms_resource_ledger_v3.py" \
  --saves "$clean_json" \
  --baseline-db-table "$INITIAL_TABLE" \
  --baseline-snapshot latest \
  --db-write-ledger --db-env "$ROOT/.env.dbshim" --db-ledger-table "$LEDGER_TABLE" \
  --session-minutes "$SESSION_MINUTES" \
  ${USE_MTIME:+--use-mtime} \
  >"$LOGS/ledger.$stamp.log" 2>&1

echo "[PIPE] done."
