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
  local raw; raw="$(python3 scripts/python/inventory_fingerprint.py --latest 2>/dev/null || true)"
  mapfile -t out < <( INV_JSON="$raw" python3 - <<'PY' 2>/dev/null || true
import json, os, re, sys
raw=os.environ.get("INV_JSON","") or ""
fp=base=mtime=saveid=""
try:
    j=json.loads(raw) if raw else {}
    fp=str(j.get("inv_fp","")); base=str(j.get("base",""))
    mtime=str(j.get("mtime","")); saveid=str(j.get("saveid",""))
except Exception:
    if raw and "\n" not in raw and "{" not in raw:
        fp=raw.strip()
if not saveid and base:
    m=re.search(r"(st_[0-9]+)", base)
    if m: saveid=m.group(1)
print(fp); print(base); print(mtime); print(saveid)
PY
  )
  if [[ ${#out[@]} -ge 4 ]]; then
    INV_FP_CAND="${out[0]}"; INV_FP_BASE="${out[1]}"; INV_FP_MTIME="${out[2]}"; INV_FP_SAVEID="${out[3]}"
  fi
  [[ -n "$INV_FP_SAVEID" ]] || INV_FP_SAVEID="default"
}
prev_invfp() { local c="${INV_FP_DIR}/${INV_FP_SAVEID}.json"; [[ -f "$c" ]] || return 0; python3 - "$c" <<'PY' 2>/dev/null || true
import json,sys
try:
  with open(sys.argv[1],encoding="utf-8") as f: j=json.load(f)
  print(j.get("inv_fp",""))
except Exception: pass
PY
}
write_invfp_cache() {
  local out="$1" fp="${2:-}" base="${3:-}" mtime="${4:-}"
  FP="$fp" BASE="$base" MTIME="$mtime" python3 - "$out" <<'PY' || exit 0
import json, os, sys, datetime
out=sys.argv[1]
doc={"generated_at":datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
     "inv_fp":os.environ.get("FP",""),
     "base":os.environ.get("BASE",""),
     "mtime":os.environ.get("MTIME","")}
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out,"w",encoding="utf-8") as f: json.dump(doc,f,indent=2)
PY
}

# --- manifest check (raw unchanged?) --------------------------------------
raw_unchanged_vs_manifest() {
  [[ -n "${INV_FP_BASE:-}" && -f "${INV_FP_BASE}" && -f "${MANIFEST}" ]] || return 1
  local cur man
  cur="$(stat -c %Y "${INV_FP_BASE}" 2>/dev/null || stat -f %m "${INV_FP_BASE}" 2>/dev/null || true)"; [[ -n "$cur" ]] || return 1
  man="$(
    python3 - "${MANIFEST}" <<'PY' 2>/dev/null || true
import json,sys
try:
  with open(sys.argv[1],encoding="utf-8") as f: j=json.load(f)
  for k in ("source_mtime","src_mtime","sourceMtime","sourceMTime","mtime"):
    if k in j: print(str(j[k])); break
except Exception: pass
PY
  )"
  [[ -n "$man" && "$cur" == "$man" ]]
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
