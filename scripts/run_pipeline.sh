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
python3 "$ROOT/scripts/python/pipeline/nms_hg_decoder.py" \
  --in "$NMS_HG_PATH" --out "$raw_json" --pretty \
  >"$LOGS/hg_decode.$stamp.log" 2>&1

# verify decode output exists and is non-empty
if [[ ! -s "$raw_json" ]]; then
  echo "[PIPE][ERROR] decode failed: $raw_json not created or empty"
  exit 3
fi

# --- clean ----------------------------------------------------------------
echo "[PIPE] cleaning -> $clean_json"
python3 "$ROOT/scripts/python/pipeline/nms_decode_clean.py" \
  --json "$raw_json" --out "$clean_json" --overwrite \
  >"$LOGS/nms_decode_clean.$stamp.log" 2>&1

# --- manifest (for runtime throttle/visibility) ---------------------------
SRC_MTIME="$(stat -c %Y "$NMS_HG_PATH" 2>/dev/null || stat -f %m "$NMS_HG_PATH" 2>/dev/null || echo "")"
python3 "$ROOT/scripts/python/pipeline/build_manifest.py" \
  --source "$NMS_HG_PATH" \
  --source-mtime "$SRC_MTIME" \
  --decoded "$raw_json" \
  --out "$ROOT/storage/decoded/_manifest_recent.json"


# --- DB env shim for importer (maps NMS_DB_* -> DB_*) -----------------------
DB_SHIM="$ROOT/.env.dbshim"
{
  echo "DB_HOST=$(strip_quotes "$(get_env DB_HOST "$(get_env NMS_DB_HOST "127.0.0.1")")")"
  echo "DB_PORT=$(strip_quotes "$(get_env DB_PORT "$(get_env NMS_DB_PORT "3306")")")"
  echo "DB_USER=$(strip_quotes "$(get_env DB_USER "$(get_env NMS_DB_USER "")")")"
  echo "DB_PASS=$(strip_quotes "$(get_env DB_PASS "$(get_env NMS_DB_PASS "")")")"
  echo "DB_NAME=$(strip_quotes "$(get_env DB_NAME "$(get_env NMS_DB_NAME "")")")"
} > "$DB_SHIM"

# Sanity: if the shim still contains unexpanded ${VAR}, rebuild via envsubst.
if grep -q '\${[A-Za-z_][A-Za-z0-9_]*}' "$DB_SHIM"; then
  # Load .env into the environment for envsubst
  set -a; [ -f "$ENV_FILE" ] && . "$ENV_FILE"; set +a
  printf '%s\n' \
    'DB_HOST=${NMS_DB_HOST}' \
    'DB_PORT=${NMS_DB_PORT}' \
    'DB_USER=${NMS_DB_USER}' \
    'DB_PASS=${NMS_DB_PASS}' \
    'DB_NAME=${NMS_DB_NAME}' \
  | envsubst > "$DB_SHIM"
fi



# --- DB imports -----------------------------------------------------------
echo "[PIPE] initial import into DB ($INITIAL_TABLE)"
# Resolve DB CLI params from env (prefer NMS_DB_*; fallback to DB_*)
DB_USER="$(strip_quotes "$(get_env DB_USER "$(get_env NMS_DB_USER "nms_user")")")"
DB_NAME="$(strip_quotes "$(get_env DB_NAME "$(get_env NMS_DB_NAME "nms_database")")")"
DB_PASS="$(strip_quotes "$(get_env DB_PASS "$(get_env NMS_DB_PASS "")")")"

# Non-interactive/background: honor .env; don't prompt
if [[ -n "$DB_PASS" ]]; then
  export MYSQL_PWD="$DB_PASS"
fi

# Interactive fallback: prompt only if no password from env and not forced noninteractive
if [[ -z "${MYSQL_PWD:-}" && -z "$DB_PASS" && -z "${NMS_NONINTERACTIVE:-}" && -t 0 && -t 1 ]]; then
  printf "[DB] Enter password for %s: " "$DB_USER" >&2
  stty -echo; IFS= read -r MYSQL_PWD; stty echo; printf "\n" >&2
  export MYSQL_PWD
fi

# Create/augment the manifest db_import_initial.py expects:
#  - keep existing fields from build_manifest.py (source_path, save_root, *_mtime, json_sha256)
#  - add out_json pointing to our full-parse file
base_name="$(basename -- "$clean_json" .clean.json)"
raw_json="${raw_json:-$ROOT/storage/decoded/${base_name}.json}"
full_json="$ROOT/output/fullparse/${base_name}.full.json"

# --- full-parse -------------------------------------------------------------
# Ensure destination directory exists and produce the out_json file the importer expects
mkdir -p "$ROOT/output/fullparse"

echo "[PIPE] full-parse -> $full_json"
python3 -m scripts.python.nms_fullparse \
  -i "$raw_json" \
  -o "$full_json" \
  >"$LOGS/fullparse.$stamp.log" 2>&1 || true

# If full-parse failed to produce output, warn (DB import uses out_json from manifest)
if [[ ! -s "$full_json" ]]; then
  echo "[warn] full-parse did not create: $full_json"
fi

mani="$ROOT/storage/decoded/_manifest_recent.json"
if [[ -s "$mani" ]]; then
  # augment existing manifest: set .items[*].out_json without dropping other fields
  tmp="$(mktemp -p "$(dirname "$mani")" "$(basename "$mani").XXXXXX")"
  jq --arg out "$full_json" --arg raw "$raw_json" '
    .items = (.items // []) |
    if (.items | length) > 0
      then .items = [ .items[] | .out_json = $out ]
      else {items:[{source_path: $raw, out_json: $out}]}
    end
  ' "$mani" > "$tmp" && { [[ -f "$tmp" ]] && mv -f "$tmp" "$mani"; }
else
  # fallback: minimal but valid shape with both keys
  cat > "$mani" <<EOF
{
  "items": [
    { "source_path": "$raw_json", "out_json": "$full_json" }
  ]
}
EOF
fi

# Import into DB (upsert snapshots, insert nms_items) — with retry on deadlock (1213)
run_initial_import() {
  local attempts=0 max=3 rc=0
  while (( attempts < max )); do
    if python3 "$ROOT/scripts/python/db_import_initial.py" \
         --manifest "$mani" \
       | mariadb -u "$DB_USER" -D "$DB_NAME" \
         >"$LOGS/initial_import.$stamp.log" 2>&1; then
      return 0
    fi
    rc=$?
    if grep -q "ERROR 1213" "$LOGS/initial_import.$stamp.log"; then
      attempts=$((attempts+1))
      echo "[PIPE][WARN] Deadlock (1213) during initial import; retry ${attempts}/${max}..."
      sleep $((attempts*2))
      continue
    fi
    return $rc
  done
  return 1
}

run_initial_import

echo "[PIPE] ledger compare -> $LEDGER_TABLE"
python3 "$ROOT/scripts/python/pipeline/nms_resource_ledger_v3.py" \
  --saves "$clean_json" \
  --baseline-db-table "$INITIAL_TABLE" \
  --baseline-snapshot latest \
  --db-write-ledger --db-env "$DB_SHIM" --db-ledger-table "$LEDGER_TABLE" \
  --session-minutes "$SESSION_MINUTES" \
  ${USE_MTIME:+--use-mtime} \
  >"$LOGS/ledger.$stamp.log" 2>&1

echo "[PIPE] done."
