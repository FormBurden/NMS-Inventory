#!/usr/bin/env bash
# NMS-Inventory — refresh runner (robust heredocs, no parser traps)
# - Safe heredocs with explicit if-guards
# - Writes inventory fingerprint cache on success AND on skip
# - Preserves your watcher/UI messages

set -Eeuo pipefail

# ---------- traps ----------
trap 'rc=$?; if [[ $rc -ne 0 ]]; then echo "[import] error"; fi' EXIT

# ---------- config ----------
DECODE_DIR=".cache/decoded"
MANIFEST="${DECODE_DIR}/_manifest_recent.json"

# Per-saveID fingerprint cache
INV_FP_DIR="${DECODE_DIR}/.fingerprint"
# If a stray file exists at the .fingerprint path, move it aside, then create the dir
if [[ -e "${INV_FP_DIR}" && ! -d "${INV_FP_DIR}" ]]; then
  echo "[runtime] WARN: ${INV_FP_DIR} exists as a file; moving aside."
  ts="$(date +%s)"
  mv -f "${INV_FP_DIR}" "${INV_FP_DIR}.bak.${ts}" 2>/dev/null || rm -f "${INV_FP_DIR}"
fi
mkdir -p "${INV_FP_DIR}"


# Optional non-inventory movement throttle (seconds)
NMS_MOVEMENT_THROTTLE_SECS="${NMS_MOVEMENT_THROTTLE_SECS:-0}"

# Pipeline candidates (first that exists will run)
PIPELINE_CANDIDATES=(
  "scripts/run_pipeline_verify.sh"
  "scripts/run_pipeline.sh"
  "scripts/import_latest.sh"
)

# ---------- utils ----------
log() { printf "%s\n" "$*"; }
die() { printf "%s\n" "$*" >&2; exit 1; }

run_pipeline() {
  local s
  for s in "${PIPELINE_CANDIDATES[@]}"; do
    if [[ -x "$s" || -f "$s" ]]; then
      bash "$s"
      return $?
    fi
  done
  die "[runtime] No pipeline runner found (run_pipeline_verify.sh|run_pipeline.sh|import_latest.sh)"
}

# Globals populated by read_invfp()
INV_FP_CAND=""
INV_FP_BASE=""
INV_FP_MTIME=""
INV_FP_SAVEID=""

read_invfp() {
  # Uses scripts/python/inventory_fingerprint.py --latest
  # Expects JSON with keys: inv_fp, base, mtime, saveid (missing keys tolerated)
  local raw
  raw="$(python3 scripts/python/inventory_fingerprint.py --latest 2>/dev/null || true)"

  # Parse JSON (or a plain-line fp) -> emit 4 lines: fp, base, mtime, saveid
  local out
  mapfile -t out < <( INV_JSON="$raw" python3 - <<'PY' 2>/dev/null || true
import json, os, re, sys
raw=os.environ.get("INV_JSON","") or ""
fp=""; base=""; mtime=""; saveid=""
try:
    j=json.loads(raw) if raw else {}
    fp=str(j.get("inv_fp",""))
    base=str(j.get("base",""))
    mtime=str(j.get("mtime",""))
    saveid=str(j.get("saveid",""))
except Exception:
    # if tool printed only the fingerprint line
    if raw and "\n" not in raw and "{" not in raw:
        fp=raw.strip()
if not saveid and base:
    m=re.search(r"(st_[0-9]+)", base)
    if m: saveid=m.group(1)
print(fp)
print(base)
print(mtime)
print(saveid)
PY
  )
  # Assign with fallbacks
  if [[ ${#out[@]} -ge 4 ]]; then
    INV_FP_CAND="${out[0]}"
    INV_FP_BASE="${out[1]}"
    INV_FP_MTIME="${out[2]}"
    INV_FP_SAVEID="${out[3]}"
  fi
  [[ -n "${INV_FP_SAVEID}" ]] || INV_FP_SAVEID="default"
}

prev_invfp() {
  # Echo previous inv_fp from cache if present
  local cache="${INV_FP_DIR}/${INV_FP_SAVEID}.json"
  [[ -f "$cache" ]] || return 0
  python3 - "$cache" <<'PY' 2>/dev/null || true
import json, sys
p=sys.argv[1]
try:
    with open(p,encoding="utf-8") as f:
        j=json.load(f)
    print(j.get("inv_fp",""))
except Exception:
    pass
PY
}

write_invfp_cache() {
  # args: <cache_path> <inv_fp> <base> <mtime>
  local out="$1" fp="${2:-}" base="${3:-}" mtime="${4:-}"
  FP="$fp" BASE="$base" MTIME="$mtime"
  if ! python3 - "$out" <<'PY'
import json, os, sys, datetime
out=sys.argv[1]
doc={
  "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
  "inv_fp": os.environ.get("FP",""),
  "base": os.environ.get("BASE",""),
  "mtime": os.environ.get("MTIME","")
}
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out,"w",encoding="utf-8") as f:
  json.dump(doc, f, indent=2)
PY
  then
    echo "[runtime] WARN: failed to write inventory fingerprint cache (${out})" >&2
  fi
}


raw_unchanged_vs_manifest() {
  # Returns 0 (true) if the current raw save mtime equals the manifest's source mtime.
  # Returns 1 otherwise (including any parsing issues).
  [[ -n "${INV_FP_BASE:-}" && -f "${INV_FP_BASE}" && -f "${MANIFEST}" ]] || return 1

  local cur man
  cur="$(stat -c %Y "${INV_FP_BASE}" 2>/dev/null || true)"
  [[ -n "${cur}" ]] || return 1

  man="$(
    python3 - "${MANIFEST}" <<'PY' 2>/dev/null || true
import json, sys
p = sys.argv[1]
try:
    with open(p, encoding="utf-8") as f:
        j = json.load(f)
    # Try common keys used by our manifest writers
    for k in ("source_mtime","src_mtime","sourceMtime","sourceMTime","mtime"):
        if k in j:
            print(str(j[k]))
            break
except Exception:
    pass
PY
  )"

  [[ -n "${man}" && "${cur}" == "${man}" ]]
}


# ---------- main ----------
mkdir -p "${DECODE_DIR}"
# ${INV_FP_DIR} is ensured earlier

read_invfp

INV_FP_CACHE="${INV_FP_DIR}/${INV_FP_SAVEID}.json"
PREV_FP="$(prev_invfp || true)"
ALLOW_IMPORT=0

if [[ -n "${INV_FP_CAND}" ]]; then
  if [[ -z "${PREV_FP}" || "${INV_FP_CAND}" != "${PREV_FP}" ]]; then
    echo "[runtime] Inventory fingerprint changed; allowing import (overrides movement throttle)."
    ALLOW_IMPORT=1
  fi
else
  echo "[runtime] No candidate inventory fingerprint from decoder; proceeding conservatively."
fi

# Non-inventory throttle
if [[ $ALLOW_IMPORT -eq 0 && "${NMS_MOVEMENT_THROTTLE_SECS}" != "0" ]]; then
  if raw_unchanged_vs_manifest; then
    echo "[runtime] Non-inventory throttle window active; skipping."
    if [[ -n "${INV_FP_CAND}" ]]; then
      write_invfp_cache "${INV_FP_CACHE}" "${INV_FP_CAND}" "${INV_FP_BASE}" "${INV_FP_MTIME}"
    fi
    echo "[import] unchanged; skipped"
    exit 0
  else
    # Raw save changed; allow import despite throttle
    ALLOW_IMPORT=1
  fi
fi


# Manifest short-circuit (only when inventory didn't change AND raw mtime equals manifest mtime)
if [[ $ALLOW_IMPORT -eq 0 ]]; then
  if raw_unchanged_vs_manifest; then
    echo "[runtime] Saves unchanged vs manifest; skipping decode/import."
    if [[ -n "${INV_FP_CAND}" ]]; then
      write_invfp_cache "${INV_FP_CACHE}" "${INV_FP_CAND}" "${INV_FP_BASE}" "${INV_FP_MTIME}"
    fi
    echo "[import] unchanged; skipped"
    exit 0
  fi
fi


# Decode + import pipeline
if run_pipeline; then
  echo "[import] success"
  if [[ -n "${INV_FP_CAND}" ]]; then
    write_invfp_cache "${INV_FP_CACHE}" "${INV_FP_CAND}" "${INV_FP_BASE}" "${INV_FP_MTIME}"
  fi
else
  : # EXIT trap will emit "[import] error"
fi
