#!/usr/bin/env bash
# NMS-Inventory — runtime refresh orchestrator
# - Folder-based .fingerprint cache
# - Skips when both inventory & raw save are unchanged
# - Delegates to run_pipeline_verify.sh → run_pipeline.sh → import_latest.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ENV_FILE="$ROOT/.env"

# --- helpers --------------------------------------------------------------
get_env(){ # get_env VAR [default]
  local k="$1" d="${2:-}" v=""
  v="$(printenv "$k" 2>/dev/null || true)"
  if [[ -z "${v:-}" && -f "$ENV_FILE" ]]; then
    v="$(grep -E "^${k}=" "$ENV_FILE" | head -n1 | cut -d= -f2- | sed -e 's/^[[:space:]]*//' || true)"
  fi
  printf "%s" "${v:-$d}"
}
strip_quotes(){ local s="${1:-}"; s="${s%\"}"; s="${s#\"}"; printf "%s" "$s"; }
log(){ printf "%s\n" "$*"; }


# --- paths ---------------------------------------------------------------
DECODE_DIR="$ROOT/storage/decoded"
MANIFEST="$DECODE_DIR/_manifest_recent.json"
INV_FP_DIR="$DECODE_DIR/.fingerprint"

mkdir -p "$DECODE_DIR"
# If .fingerprint exists as a file, move aside and create a directory
if [[ -e "${INV_FP_DIR}" && ! -d "${INV_FP_DIR}" ]]; then
  log "[runtime] WARN: ${INV_FP_DIR} exists as a file; moving aside."
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  bak="${INV_FP_DIR}.bak.${ts}.$$"
  if ! mv -f -- "${INV_FP_DIR}" "${bak}" 2>/dev/null; then
    log "[runtime] WARN: failed to move stale file; removing it so the directory can be created."
    rm -f -- "${INV_FP_DIR}"
  fi
fi
mkdir -p -- "${INV_FP_DIR}"

# --- throttle settings ----------------------------------------------------
NMS_NONINV_THROTTLE_SEC="$(strip_quotes "$(get_env NMS_NONINV_THROTTLE_SEC 0)")"

# --- pipeline chooser -----------------------------------------------------
run_pipeline() {
  for s in scripts/run_pipeline_verify.sh scripts/run_pipeline.sh scripts/import_latest.sh; do
    if [[ -x "$s" || -f "$s" ]]; then bash "$s"; return $?; fi
  done
  log "[runtime] ERROR: no pipeline runner found"; return 127
}

# --- inventory fingerprint I/O -------------------------------------------
INV_FP_CAND="" INV_FP_BASE="" INV_FP_MTIME="" INV_FP_SAVEID=""
read_invfp() {
  # Expect scripts/python/inventory_fingerprint.py --latest (JSON or plain line)
  local raw; raw="$(python3 scripts/python/runtime/inventory_fingerprint.py --latest 2>/dev/null || true)"
  mapfile -t out < <( printf '%s' "$raw" | python3 scripts/python/runtime/invfp_to_fields.py )

  if [[ ${#out[@]} -ge 4 ]]; then
    INV_FP_CAND="${out[0]}"; INV_FP_BASE="${out[1]}"; INV_FP_MTIME="${out[2]}"; INV_FP_SAVEID="${out[3]}"
  fi
  [[ -n "$INV_FP_SAVEID" ]] || INV_FP_SAVEID="default"
}
prev_invfp() { local c="${INV_FP_DIR}/${INV_FP_SAVEID}.json"; [[ -f "$c" ]] || return 0; python3 scripts/python/runtime/read_prev_invfp.py "$c"; }


write_invfp_cache() {
  local out="$1" fp="${2:-}" base="${3:-}" mtime="${4:-}"
  python3 scripts/python/runtime/write_invfp_cache.py --out "$out" --inv-fp "$fp" --base "$base" --mtime "$mtime" || true
}


# --- manifest check (raw unchanged?) --------------------------------------
man="$(python3 scripts/python/runtime/read_manifest_mtime.py "${MANIFEST}" 2>/dev/null || true)"

raw_unchanged_vs_manifest() {
  # True when the raw save's mtime matches the last manifest's recorded mtime.
  # Requires both values to be non-empty (epoch seconds as strings).
  [[ -n "${man:-}" && -n "${INV_FP_MTIME:-}" ]] || return 1
  [[ "$man" == "$INV_FP_MTIME" ]]
}

# --- main -----------------------------------------------------------------
read_invfp
INV_FP_CACHE="${INV_FP_DIR}/${INV_FP_SAVEID}.json"
PREV_FP="$(prev_invfp || true)"
ALLOW_IMPORT=0

if [[ -n "${INV_FP_CAND}" ]]; then
  if [[ -z "${PREV_FP}" || "${INV_FP_CAND}" != "${PREV_FP}" ]]; then
    log "[runtime] Inventory fingerprint changed; allowing import."
    ALLOW_IMPORT=1
  fi
else
  log "[runtime] No candidate inventory fingerprint from decoder; proceeding conservatively."
fi

# Non-inventory throttle: if inv unchanged AND raw mtime same as manifest, skip
if [[ $ALLOW_IMPORT -eq 0 && "${NMS_NONINV_THROTTLE_SEC}" != "0" ]]; then
  if raw_unchanged_vs_manifest; then
    log "[runtime] Non-inventory throttle window active; skipping."
    [[ -n "${INV_FP_CAND}" ]] && write_invfp_cache "${INV_FP_CACHE}" "${INV_FP_CAND}" "${INV_FP_BASE}" "${INV_FP_MTIME}"
    echo "[import] unchanged; skipped"
    exit 0
  fi
fi

# Last-chance: if inv unchanged but raw changed, allow import
if [[ $ALLOW_IMPORT -eq 0 ]]; then
  if ! raw_unchanged_vs_manifest; then
    ALLOW_IMPORT=1
  fi
fi

# Run pipeline
if [[ $ALLOW_IMPORT -eq 1 ]]; then
  echo "[verify] running pipeline with xtrace..."
  set -x
  if run_pipeline; then
    set +x
    echo "[import] success"
    [[ -n "${INV_FP_CAND}" ]] && write_invfp_cache "${INV_FP_CACHE}" "${INV_FP_CAND}" "${INV_FP_BASE}" "${INV_FP_MTIME}"
    exit 0
  else
    rc=$?; set +x; exit "$rc"
  fi
else
  log "[runtime] Nothing to import."
  [[ -n "${INV_FP_CAND}" ]] && write_invfp_cache "${INV_FP_CACHE}" "${INV_FP_CAND}" "${INV_FP_BASE}" "${INV_FP_MTIME}"
  echo "[import] unchanged; skipped"
fi
