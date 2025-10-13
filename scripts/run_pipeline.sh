#!/usr/bin/env bash
# NMS-Inventory — decode → clean → DB import (+manifest)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ENV_FILE="$ROOT/.env"

# --- helpers ---------------------------------------------------------------
get_env() { # get_env VAR [default]
  local k="$1" d="${2:-}" v=""
  # read from environment safely (no nounset/indirect-expansion pitfalls)
  v="$(printenv "$k" 2>/dev/null || true)"
  if [[ -z "${v:-}" && -f "$ENV_FILE" ]]; then
    # first matching VAR=VALUE line from .env
    v="$(grep -E "^${k}=" "$ENV_FILE" | head -n1 | cut -d= -f2- | sed -e 's/^[[:space:]]*//' || true)"
  fi
  printf "%s" "${v:-$d}"
}
strip_quotes(){ local s="${1:-}"; s="${s%\"}"; s="${s#\"}"; printf "%s" "$s"; }

# --- config ---------------------------------------------------------------
NMS_SAVE_ROOT="$(strip_quotes "$(get_env NMS_SAVE_ROOT "")")"
NMS_PROFILE="$(strip_quotes "$(get_env NMS_PROFILE "")")"
NMS_HG_PATH="$(strip_quotes "$(get_env NMS_HG_PATH "")")"
INITIAL_TABLE="$(get_env INITIAL_TABLE nms_initial_items)"
LEDGER_TABLE="$(get_env LEDGER_TABLE nms_ledger_deltas)"
USE_MTIME="$(get_env USE_MTIME 1)"
SESSION_MINUTES="$(get_env SESSION_MINUTES 60)"


DEC="$ROOT/storage/decoded"
CLEAN="$ROOT/storage/cleaned"
LOGS="$ROOT/storage/logs"
mkdir -p "$DEC" "$CLEAN" "$LOGS"

# --- resolve raw save path (accept file OR directory) ---------------------
HG_DIR=""
if [[ -z "${NMS_HG_PATH:-}" ]]; then
  HG_DIR="${NMS_SAVE_ROOT%/}/${NMS_PROFILE}"
elif [[ -d "${NMS_HG_PATH}" ]]; then
  HG_DIR="${NMS_HG_PATH%/}"
fi
if [[ -n "$HG_DIR" ]]; then
  CAND="$(ls -1t "$HG_DIR"/save*.hg 2>/dev/null | head -n1 || true)"
  [[ -n "$CAND" ]] && NMS_HG_PATH="$CAND"
fi
[[ -n "${NMS_HG_PATH:-}" && -f "${NMS_HG_PATH}" ]] || { echo "[PIPE][ERROR] missing save*.hg (NMS_HG_PATH)"; exit 2; }

# --- outputs --------------------------------------------------------------
stamp="$(date -u +%Y-%m-%d_%H-%M-%S)"
base="$(basename "$NMS_HG_PATH")"
case "$base" in
  save2.hg) out_name="save2.json" ;;
  save.hg)  out_name="save.json" ;;
  *)        out_name="save_${stamp}.json" ;;
esac
raw_json="$DEC/$out_name"
clean_json="$CLEAN/${out_name%.json}.clean.json"

# --- decode ---------------------------------------------------------------
echo "[PIPE] decoding -> $raw_json"
python3 "$ROOT/scripts/python/nms_hg_decoder.py" \
  --in "$NMS_HG_PATH" --out "$raw_json" --pretty \
  >"$LOGS/hg_decode.$stamp.log" 2>&1

# verify decode output exists and is non-empty
if [[ ! -s "$raw_json" ]]; then
  echo "[PIPE][ERROR] decode failed: $raw_json not created or empty"
  exit 3
fi

# --- clean ----------------------------------------------------------------
echo "[PIPE] cleaning -> $clean_json"
python3 "$ROOT/scripts/python/nms_decode_clean.py" \
  --json "$raw_json" --out "$clean_json" --overwrite \
  >"$LOGS/nms_decode_clean.$stamp.log" 2>&1

# --- manifest (for runtime throttle/visibility) ---------------------------
SRC_MTIME="$(stat -c %Y "$NMS_HG_PATH" 2>/dev/null || stat -f %m "$NMS_HG_PATH" 2>/dev/null || echo "")"
python3 "$ROOT/scripts/python/build_manifest.py" \
  --source "$NMS_HG_PATH" \
  --source-mtime "$SRC_MTIME" \
  --decoded "$raw_json" \
  --out "$ROOT/storage/decoded/_manifest_recent.json" || true


# --- DB env shim for importer (maps NMS_DB_* -> DB_*) -----------------------
DB_SHIM="$ROOT/.env.dbshim"
{
  echo "DB_HOST=$(strip_quotes "$(get_env DB_HOST "$(get_env NMS_DB_HOST "127.0.0.1")")")"
  echo "DB_PORT=$(strip_quotes "$(get_env DB_PORT "$(get_env NMS_DB_PORT "3306")")")"
  echo "DB_USER=$(strip_quotes "$(get_env DB_USER "$(get_env NMS_DB_USER "")")")"
  echo "DB_PASS=$(strip_quotes "$(get_env DB_PASS "$(get_env NMS_DB_PASS "")")")"
  echo "DB_NAME=$(strip_quotes "$(get_env DB_NAME "$(get_env NMS_DB_NAME "")")")"
} > "$DB_SHIM"


# --- DB imports -----------------------------------------------------------
echo "[PIPE] initial import into DB ($INITIAL_TABLE)"
python3 "$ROOT/scripts/python/nms_resource_ledger_v3.py" --initial \
  --saves "$clean_json" \
  --db-import --db-env "$DB_SHIM" --db-table "$INITIAL_TABLE" \
  ${USE_MTIME:+--use-mtime} \
  >"$LOGS/initial_import.$stamp.log" 2>&1

echo "[PIPE] ledger compare -> $LEDGER_TABLE"
python3 "$ROOT/scripts/python/nms_resource_ledger_v3.py" \
  --saves "$clean_json" \
  --baseline-db-table "$INITIAL_TABLE" \
  --baseline-snapshot latest \
  --db-write-ledger --db-env "$DB_SHIM" --db-ledger-table "$LEDGER_TABLE" \
  --session-minutes "$SESSION_MINUTES" \
  ${USE_MTIME:+--use-mtime} \
  >"$LOGS/ledger.$stamp.log" 2>&1

echo "[PIPE] done."
