#!/usr/bin/env bash
set -euo pipefail
trap 'rc=$?; if [[ $rc -ne 0 ]]; then echo "[import] error"; fi' EXIT

# ---- Config & .env ----------------------------------------------------------
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Load .env if present
if [[ -f .env ]]; then
  # shellcheck source=/dev/null
  source .env
fi

# Defaults (override via .env)
NMS_DECODER="${NMS_DECODER:-$PROJECT_ROOT/scripts/python/nms_hg_decoder.py}"
DEFAULT_SAVES="${NMS_SAVE_ROOT%/}/${NMS_PROFILE}"
NMS_SAVES_DIRS="${NMS_SAVES_DIRS:-$DEFAULT_SAVES}"

NMS_DB_NAME="${NMS_DB_NAME:-nms_database}"
NMS_DB_USER="${NMS_DB_USER:-nms_user}"
# Optional for non-interactive imports:
# NMS_DB_PASS="yourpassword"

# Skip when unchanged (1 = on)
NMS_SKIP_DECODE_ON_UNCHANGED="${NMS_SKIP_DECODE_ON_UNCHANGED:-1}"
# Age window for “recent” (days)
NMS_CUTOFF_DAYS="${NMS_CUTOFF_DAYS:-30}"
# Debug the fingerprints we compare (0/1)
NMS_DEBUG_FINGERPRINTS="${NMS_DEBUG_FINGERPRINTS:-0}"

LOG_DIR=".cache/logs"
DECODED_DIR=".cache/decoded"
MANIFEST="${DECODED_DIR}/_manifest_recent.json"

# Raw-SHA guard (fast content check to avoid needless decode)
NMS_USE_RAW_SHA_GUARD="${NMS_USE_RAW_SHA_GUARD:-1}"
RAW_SHA_CACHE="${DECODED_DIR}/_rawsha.json"
# Non-inventory throttle knobs
NMS_NONINV_THROTTLE_SEC="${NMS_NONINV_THROTTLE_SEC:-600}"
NMS_NONINV_SIZE_DELTA_MIN="${NMS_NONINV_SIZE_DELTA_MIN:-16384}"
# Inventory fingerprint guard (per-profile cache under storage/decoded/.fingerprint)
NMS_USE_INVENTORY_FP_GUARD="${NMS_USE_INVENTORY_FP_GUARD:-1}"
INV_FP_DIR="${DECODED_DIR}/.fingerprint/${NMS_PROFILE}"



mkdir -p "$LOG_DIR" "$DECODED_DIR"

# ---- Expand & validate save directories (colon-separated, spaces-safe) ------
IFS=':' read -r -a CANDIDATE_DIRS <<< "$NMS_SAVES_DIRS"
FILTERED_DIRS=()
for d in "${CANDIDATE_DIRS[@]}"; do
  if [[ -d "$d" ]]; then
    FILTERED_DIRS+=("$d")
  else
    echo "[runtime] WARN: not a directory, skipping: $d"
  fi
done
if [[ ${#FILTERED_DIRS[@]} -eq 0 ]]; then
  echo "[runtime] ERROR: No valid save directories to scan. Check NMS_SAVES_DIRS." >&2
  exit 1
fi

# ---- Build candidate fingerprint from top-2 REAL saves (save*.hg) ------------
cutoff_ts="$(date -u -d "-${NMS_CUTOFF_DAYS} days" +%s)"

mapfile -t recent_hg < <(
  find "${FILTERED_DIRS[@]}" -type f -name 'save*.hg' -printf '%T@|%p\n' 2>/dev/null \
    | awk -F'|' -v c="$cutoff_ts" '{ if (int($1) >= c) print; }' \
    | sort -nr \
    | head -n 2
)

declare -a cand_strs_utc=()
declare -a cand_epochs=()
for line in "${recent_hg[@]:-}"; do
  ts="${line%%|*}"
  path="${line#*|}"
  [[ -n "${ts:-}" && -n "${path:-}" ]] || continue
  base="${path##*/}"
  epoch="${ts%.*}"
  # IMPORTANT: format the string in UTC to match manifest’s source_mtime
  mtime_str_utc="$(TZ=UTC date -u -d "@${epoch}" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || true)"
  [[ -n "$mtime_str_utc" ]] || continue
  cand_strs_utc+=("${base},${mtime_str_utc}")
  cand_epochs+=("${base},${epoch}")
done

join_sorted() {
  if [[ $# -eq 0 ]]; then
    echo ""
    return
  fi
  printf '%s\n' "$@" | sort | paste -sd'|' -
}
candidate_fp_str="$(join_sorted "${cand_strs_utc[@]:-}")"
candidate_fp_epoch="$(join_sorted "${cand_epochs[@]:-}")"

# ---- Compute raw SHA256 for latest save*.hg (content guard) -------------------
declare -a cand_raw_pairs=()    # "basename,sha"
declare -a cand_raw_records=()  # "base,sha,fullpath,mtime_utc,size"

hash_file_py() {
  python3 - <<'PY' "$1"
import hashlib, sys
p=sys.argv[1]
h=hashlib.sha256()
with open(p,'rb') as f:
  for chunk in iter(lambda: f.read(1<<20), b''):
    h.update(chunk)
print(h.hexdigest())
PY
}

for line in "${recent_hg[@]:-}"; do
  path="${line#*|}"
  [[ -f "$path" ]] || continue
  base="${path##*/}"
  sha="$(hash_file_py "$path" 2>/dev/null || echo "")"
  size="$(stat -c%s "$path" 2>/dev/null || wc -c < "$path" 2>/dev/null || echo 0)"
  # find the UTC mtime we already computed earlier for this base
  # fall back to stat -> UTC if not found (shouldn't happen)
  mtime_utc=""
  for ce in "${cand_strs_utc[@]:-}"; do
    [[ "${ce%%,*}" == "$base" ]] && mtime_utc="${ce#*,}" && break
  done
  if [[ -z "$mtime_utc" ]]; then
    epoch="$(stat -c%Y "$path" 2>/dev/null || echo 0)"
    mtime_utc="$(TZ=UTC date -u -d "@${epoch}" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "")"
  fi
  if [[ -n "$sha" ]]; then
    cand_raw_pairs+=("${base},${sha}")
    cand_raw_records+=("${base},${sha},${path},${mtime_utc},${size}")
  fi
done

candidate_raw_fp="$(join_sorted "${cand_raw_pairs[@]:-}")"
# Export the detailed records for cache update after a successful decode/import
export CAND_RAW_RECORDS="$(printf '%s\n' "${cand_raw_records[@]:-}" | sort | paste -sd'|' -)"


# ---- Extract manifest fingerprints (treat source_mtime as UTC) ---------------
manifest_fp_str=""
manifest_fp_epoch=""

if [[ -s "$MANIFEST" ]]; then
  if command -v jq >/dev/null 2>&1; then
    # String form (basename,source_mtime) — manifest times are UTC-like strings
    manifest_fp_str="$(jq -r '
      .items
      | map( ((.source_path|split("/")|last) + "," + .source_mtime) )
      | sort | join("|")
    ' "$MANIFEST")"

    # Epoch form (basename,epoch) — parse source_mtime as UTC
    mapfile -t _m_epochs < <(
      jq -r '.items[] | "\((.source_path|split("/")|last))\t\(.source_mtime)"' "$MANIFEST" \
      | while IFS=$'\t' read -r base sm; do
          if epoch="$(TZ=UTC date -u -d "$sm" +%s 2>/dev/null)"; then
            printf '%s,%s\n' "$base" "$epoch"
          fi
        done | sort
    )
    manifest_fp_epoch="$(paste -sd'|' <(printf '%s\n' "${_m_epochs[@]:-}"))"
  else
    # Python fallback builds only the string fingerprint (no epoch compare)
    manifest_fp_str="$(python3 - <<'PY'
import json, os, sys
p=".cache/decoded/_manifest_recent.json"
try:
    with open(p,'r',encoding='utf-8') as f:
        j=json.load(f)
except Exception:
    print("")
    sys.exit(0)
lines=[]
for it in j.get('items', []):
    sp=it.get('source_path','')
    sm=it.get('source_mtime','')
    if sp and sm:
        lines.append(f"{os.path.basename(sp)},{sm}")
print("|".join(sorted(lines)))
PY
)"
  fi
fi

# ---- Debug log ---------------------------------------------------------------
if [[ "$NMS_DEBUG_FINGERPRINTS" == "1" ]]; then
  {
    echo "---- runtime fingerprints ----"
    echo "candidate_fp_str=${candidate_fp_str}"
    echo "manifest_fp_str =${manifest_fp_str}"
    echo "candidate_fp_epoch=${candidate_fp_epoch}"
    echo "manifest_fp_epoch =${manifest_fp_epoch}"
    echo "--------------------------------"
  } >> "${LOG_DIR}/runtime.debug.log"
fi

# ---- Early skip guard (raw SHA of save*.hg) -----------------------------------
if [[ "${NMS_USE_RAW_SHA_GUARD:-1}" == "1" && -n "${candidate_raw_fp:-}" ]]; then
  cache_raw_fp=""
  if [[ -s "$RAW_SHA_CACHE" ]]; then
    if command -v jq >/dev/null 2>&1; then
      cache_raw_fp="$(jq -r '.items | map((.base + "," + .sha256)) | sort | join("|")' "$RAW_SHA_CACHE" 2>/dev/null || true)"
    else
      cache_raw_fp="$(python3 - <<'PY'
import json,sys
p=".cache/decoded/_rawsha.json"
try:
    j=json.load(open(p,"r",encoding="utf-8"))
    pairs = ["%s,%s"%(it.get("base",""), it.get("sha256","")) for it in j.get("items",[])]
    print("|".join(sorted([x for x in pairs if x and "," in x])))
except Exception:
    print("")
PY
)"
    fi
  fi
  if [[ -n "$cache_raw_fp" && "$candidate_raw_fp" == "$cache_raw_fp" ]]; then
    echo "[runtime] Raw SHA unchanged for latest saves; skipping decode/import."
    exit 0
  fi
fi

# ---- Inventory-only fingerprint (bypass throttle if inventory actually changed) ----
if [[ "${NMS_USE_INVENTORY_FP_GUARD:-1}" == "1" && -n "${recent_hg[0]:-}" ]]; then
  latest_path="${recent_hg[0]#*|}"                 # "/.../save2.hg"
  if [[ -f "$latest_path" ]]; then
    base="$(basename "$latest_path")"              # "save2.hg"
    save_id="${base%.hg}"                          # "save2"
    INV_FP_SAVEID="$save_id"
    export INV_FP_SAVEID
    export INV_FP_BASE="$base"

    # Compute current fingerprint from the save itself
    inv_fp="$(python3 -u scripts/python/inventory_fingerprint.py --hg "$latest_path" 2>/dev/null || echo "")"
    if [[ -n "$inv_fp" ]]; then
      export INV_FP_CAND="$inv_fp"
      # locate the UTC mtime (for cache metadata)
      inv_mtime_utc=""
      for ce in "${cand_strs_utc[@]:-}"; do
        [[ "${ce%%,*}" == "$base" ]] && inv_mtime_utc="${ce#*,}" && break
      done
      export INV_FP_MTIME="${inv_mtime_utc:-}"

      # Compare with last stored fingerprint for this profile/save
      INV_FP_CACHE="${INV_FP_DIR}/${save_id}.json"
      prev_inv_fp=""
      if [[ -s "$INV_FP_CACHE" ]]; then
        if command -v jq >/dev/null 2>&1; then
          prev_inv_fp="$(jq -r '.inv_fp // ""' "$INV_FP_CACHE" 2>/dev/null || true)"
        else
          prev_inv_fp="$(python3 - <<'PY'
import json,sys,os
p=os.environ.get("INV_FP_CACHE","")
try: print(json.load(open(p,"r",encoding="utf-8")).get("inv_fp",""))
except Exception: print("")
PY
)"
        fi
      fi

      if [[ -z "$prev_inv_fp" || "$inv_fp" != "$prev_inv_fp" ]]; then
        export NMS_INV_FORCE_ALLOW="1"
        echo "[runtime] Inventory fingerprint changed; allowing import (overrides movement throttle)."
      else
        echo "[runtime] Inventory fingerprint unchanged."
      fi
    fi
  fi
fi


# ---- Non-inventory throttle (time-window + small size delta) -------------------
# If saves changed but last decode was < window AND the raw-size deltas are small,
# skip now; we'll allow one decode when the window expires so coords/position still update sometimes.
NMS_NONINV_THROTTLE_SEC="${NMS_NONINV_THROTTLE_SEC:-600}"      # 10 minutes
NMS_NONINV_SIZE_DELTA_MIN="${NMS_NONINV_SIZE_DELTA_MIN:-16384}" # 16 KiB

if [[ -z "${NMS_INV_FORCE_ALLOW:-}" && -n "${CAND_RAW_RECORDS:-}" ]]; then
  if python3 - "$RAW_SHA_CACHE" "$MANIFEST" "$NMS_NONINV_THROTTLE_SEC" "$NMS_NONINV_SIZE_DELTA_MIN" <<'PY'
import json, os, sys, time
cache, manifest, win, thresh = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
now = int(time.time())
try: last = int(os.path.getmtime(manifest))
except Exception: last = 0
# Expired window? allow.
if now - last >= win:
    print("ALLOW age"); sys.exit(0)
# Build prev sizes from cache
prev = {}
try:
    with open(cache, "r", encoding="utf-8") as f:
        j = json.load(f)
    for it in j.get("items", []):
        b = it.get("base"); s = it.get("size", 0)
        if b is not None:
            try: prev[b] = int(s)
            except: prev[b] = 0
except Exception:
    prev = {}
# Check candidate sizes vs prev
pairs = os.environ.get("CAND_RAW_RECORDS","").split("|")
small = True
for rec in pairs:
    if not rec: continue
    base, _sha, _path, _mtime, size = (rec.split(",", 4) + ["","","","",""])[:5]
    try: size = int(size)
    except: size = 0
    if base not in prev:
        # new base; treat as potentially large if it itself is big
        if size >= thresh: small = False; break
        else: continue
    if abs(size - prev[base]) >= thresh:
        small = False; break
print("SKIP" if small else "ALLOW")
PY
  then
    echo "[runtime] Non-inventory throttle window active; skipping."
    echo "[import] skipped (non-inventory throttle)"
    exit 0
  fi
fi


# ---- Skip guard (string OR epoch match) --------------------------------------
should_skip=0
if [[ "$NMS_SKIP_DECODE_ON_UNCHANGED" == "1" ]]; then
  if [[ -n "$candidate_fp_str" && -n "$manifest_fp_str" && "$candidate_fp_str" == "$manifest_fp_str" ]]; then
    should_skip=1
  elif [[ -n "$candidate_fp_epoch" && -n "$manifest_fp_epoch" && "$candidate_fp_epoch" == "$manifest_fp_epoch" ]]; then
    should_skip=1
  fi
fi

if [[ "$should_skip" == "1" ]]; then
  echo "[runtime] Saves unchanged vs manifest; skipping decode/import."
  echo "[import] unchanged; skipped"
  exit 0
fi

# ---- Decode (writes .cache/decoded/_manifest_recent.json) --------------------
echo "[runtime] Decoding latest saves → ${DECODED_DIR}"
python3 -u scripts/python/nms_import_initial.py --decode \
  --decoder "$NMS_DECODER" \
  --saves-dirs "$NMS_SAVES_DIRS" \
  >> "${LOG_DIR}/decode.log" 2>&1

# --- Update raw-SHA cache for latest saves (for next runs) ---
if [[ "${NMS_USE_RAW_SHA_GUARD:-1}" == "1" && -n "${CAND_RAW_RECORDS:-}" ]]; then
  python3 - "$RAW_SHA_CACHE" <<'PY' || {
    echo "[runtime] WARN: failed to update raw-SHA cache (${RAW_SHA_CACHE})" >&2
  }
import json, os, sys, datetime
out = sys.argv[1]
pairs = os.environ.get("CAND_RAW_RECORDS","")  # "base,sha,path,mtime,size|base2,sha2,..."
items=[]
for rec in filter(None, pairs.split("|")):
    parts = rec.split(",", 4)
    if len(parts) < 5:
        continue
    base, sha, path, mtime, size = parts
    try:
        size = int(size)
    except Exception:
        size = 0
    items.append({"base": base, "sha256": sha, "path": path, "mtime": mtime, "size": size})
doc = {"generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "items": items}
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    json.dump(doc, f, indent=2)
PY
fi


# ---- Import to DB ------------------------------------------------------------
if [[ -s "$MANIFEST" ]]; then
  echo "[runtime] Importing decoded manifest → MariaDB (${NMS_DB_NAME})"
  DB_ARGS=(-u "$NMS_DB_USER" -D "$NMS_DB_NAME")
  if [[ -n "${NMS_DB_PASS:-}" ]]; then
    DB_ARGS+=(-p"$NMS_DB_PASS")
  elif [[ -t 0 ]]; then
    DB_ARGS+=(-p)
  elif [[ ! -f "$HOME/.my.cnf" ]]; then
    echo "[runtime] WARN: No password in .env and non-interactive session; skipping DB import. Consider NMS_DB_PASS in .env or ~/.my.cnf." >&2
    echo "[import] skipped (no DB credentials)"
    exit 0
  fi

  # Run the import; with 'pipefail' on, this fails the script if mariadb returns non-zero.
  python3 -u scripts/python/db_import_initial.py \
    --manifest "$MANIFEST" \
    2>> "${LOG_DIR}/import.stderr.log" \
    | mariadb "${DB_ARGS[@]}" 1>/dev/null

  echo "[import] success"

  # Update inventory fingerprint cache if we computed one this run.
  # This must never cause the whole refresh to fail — guard it.
  if [[ -n "${INV_FP_CAND:-}" ]]; then
    INV_FP_CACHE="${INV_FP_DIR}/${INV_FP_SAVEID}.json"
    python3 - "$INV_FP_CACHE" <<'PY' || {
      echo "[runtime] WARN: failed to write inventory fingerprint cache (${INV_FP_CACHE})" >&2
    }
import json, os, sys, datetime
out = sys.argv[1]
doc = {
  "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
  "inv_fp": os.environ.get("INV_FP_CAND",""),
  "base": os.environ.get("INV_FP_BASE",""),
  "mtime": os.environ.get("INV_FP_MTIME","")
}
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out,"w",encoding="utf-8") as f:
    json.dump(doc, f, indent=2)
PY
  fi

else
  echo "[runtime] ERROR: Manifest not found after decode: $MANIFEST" >&2
  echo "[import] error (manifest missing)"
  exit 1
fi

echo "[runtime] Done."
