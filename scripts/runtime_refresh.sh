#!/usr/bin/env bash
set -euo pipefail

# ---- Config & .env ----------------------------------------------------------
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Load .env if present
if [[ -f .env ]]; then
  # shellcheck source=/dev/null
  source .env
fi

# Defaults (override via .env)
NMS_DECODER="${NMS_DECODER:-/mnt/Unlimited-Gaming/Modding/No-Mans-Sky/NMS-Save-Decoder-main/nmssavetool.py}"
DEFAULT_SAVES="/mnt/Unlimited-Gaming/SteamLibrary/steamapps/compatdata/275850/pfx/drive_c/users/steamuser/Application Data/HelloGames/NMS/st_76561198065088580"
NMS_SAVES_DIRS="${NMS_SAVES_DIRS:-$DEFAULT_SAVES}"

NMS_DB_NAME="${NMS_DB_NAME:-nms_database}"
NMS_DB_USER="${NMS_DB_USER:-nms_user}"
# Optional for non-interactive imports:
# NMS_DB_PASS="yourpassword"

NMS_SKIP_DECODE_ON_UNCHANGED="${NMS_SKIP_DECODE_ON_UNCHANGED:-1}"
NMS_CUTOFF_DAYS="${NMS_CUTOFF_DAYS:-30}"
NMS_DEBUG_FINGERPRINTS="${NMS_DEBUG_FINGERPRINTS:-0}"
# Use your local TZ to format/parse times so they match the manifest
NMS_LOCAL_TZ="${NMS_LOCAL_TZ:-America/Denver}"

LOG_DIR=".cache/logs"
DECODED_DIR=".cache/decoded"
MANIFEST="${DECODED_DIR}/_manifest_recent.json"

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
cutoff_ts="$(date -d "-${NMS_CUTOFF_DAYS} days" +%s)"

mapfile -t recent_hg < <(
  find "${FILTERED_DIRS[@]}" -type f -name 'save*.hg' -printf '%T@|%p\n' 2>/dev/null \
    | awk -F'|' -v c="$cutoff_ts" '{ if (int($1) >= c) print; }' \
    | sort -nr \
    | head -n 2
)

declare -a cand_strs=()
declare -a cand_epochs=()
for line in "${recent_hg[@]:-}"; do
  ts="${line%%|*}"
  path="${line#*|}"
  [[ -n "${ts:-}" && -n "${path:-}" ]] || continue
  base="${path##*/}"
  epoch="${ts%.*}"
  # Format mtime string in configured local TZ to align with manifest
  mtime_str="$(TZ="$NMS_LOCAL_TZ" date -d "@${epoch}" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || true)"
  [[ -n "$mtime_str" ]] || continue
  cand_strs+=("${base},${mtime_str}")
  cand_epochs+=("${base},${epoch}")
done

# sort helpers
join_sorted() {
  if [[ $# -eq 0 ]]; then
    echo ""
    return
  fi
  printf '%s\n' "$@" | sort | paste -sd'|' -
}

candidate_fp_str="$(join_sorted "${cand_strs[@]:-}")"
candidate_fp_epoch="$(join_sorted "${cand_epochs[@]:-}")"

# ---- Extract manifest fingerprints (string + epoch) --------------------------
manifest_fp_str=""
manifest_fp_epoch=""

if [[ -s "$MANIFEST" ]]; then
  if command -v jq >/dev/null 2>&1; then
    # string form (basename,source_mtime)
    manifest_fp_str="$(jq -r '
      .items
      | map( ((.source_path|split("/")|last) + "," + .source_mtime) )
      | sort | join("|")
    ' "$MANIFEST")"

    # epoch form (basename,epoch) using NMS_LOCAL_TZ for parsing
    mapfile -t _m_epochs < <(
      jq -r '.items[] | "\((.source_path|split("/")|last))\t\(.source_mtime)"' "$MANIFEST" \
      | while IFS=$'\t' read -r base sm; do
          if epoch="$(TZ="$NMS_LOCAL_TZ" date -d "$sm" +%s 2>/dev/null)"; then
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

# ---- Skip guard --------------------------------------------------------------
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
  exit 0
fi

# ---- Decode (writes .cache/decoded/_manifest_recent.json) --------------------
echo "[runtime] Decoding latest saves → ${DECODED_DIR}"
python3 -u scripts/python/nms_import_initial.py --decode \
  --decoder "$NMS_DECODER" \
  --saves-dirs "$NMS_SAVES_DIRS" \
  >> "${LOG_DIR}/decode.log" 2>&1

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
    exit 0
  fi

  python3 -u scripts/python/db_import_initial.py \
    --manifest "$MANIFEST" \
    2>> "${LOG_DIR}/import.stderr.log" \
    | mariadb "${DB_ARGS[@]}" 1>/dev/null
else
  echo "[runtime] ERROR: Manifest not found after decode: $MANIFEST" >&2
  exit 1
fi

echo "[runtime] Done."
