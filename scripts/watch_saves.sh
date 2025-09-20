#!/usr/bin/env bash
set -euo pipefail

# --- Config (edit if your paths differ) ---
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DECODE_ROOT="/mnt/Unlimited-Gaming/Modding/No-Mans-Sky/NMS-Save-Decoder-main"
NMSSAVETOOL="$DECODE_ROOT/nmssavetool.py"
DECODER="$ROOT_DIR/scripts/python/nms_decode_clean.py"
OUT_DIR="$ROOT_DIR/.cache/decoded"

# If you have multiple st_* dirs, set SAVE_DIR explicitly via env var before running.
SAVE_DIR="${SAVE_DIR:-}"

# --- Checks ---
command -v inotifywait >/dev/null 2>&1 || {
  echo "[ERR] inotifywait not found. Install: sudo pacman -S inotify-tools  (or your distro equivalent)" >&2
  exit 1
}
[[ -x "$DECODER" || -f "$DECODER" ]] || { echo "[ERR] Decoder not found: $DECODER"; exit 1; }
[[ -f "$NMSSAVETOOL" ]] || { echo "[ERR] nmssavetool not found: $NMSSAVETOOL"; exit 1; }

if [[ -z "$SAVE_DIR" ]]; then
  # Auto-pick the first st_* directory
  SAVE_DIR="$(ls -d "$DECODE_ROOT"/st_* 2>/dev/null | head -n1 || true)"
  [[ -n "$SAVE_DIR" ]] || { echo "[ERR] No st_* directory under $DECODE_ROOT"; exit 1; }
fi
[[ -d "$SAVE_DIR" ]] || { echo "[ERR] SAVE_DIR does not exist: $SAVE_DIR"; exit 1; }

mkdir -p "$OUT_DIR"

echo "[OK] Watching: $SAVE_DIR"
echo "[OK] Output to: $OUT_DIR"
echo "[OK] Decoder: $DECODER"
echo "[OK] Tool:    $NMSSAVETOOL"

LOCK="$OUT_DIR/.watch_decode.lock"

decode_one() {
  local hg="$1"
  local base fname out
  fname="$(basename "$hg")"
  base="${fname%.hg}"
  out="$OUT_DIR/${base}.clean.json"

  # Serialize per-file decode to avoid collisions
  exec 9>"$LOCK"
  flock -n 9 || true

  echo "[INFO] $(date +'%F %T') decoding $fname -> $(basename "$out")"
  python3 "$DECODER" \
    --hg "$hg" \
    --nmssavetool "$NMSSAVETOOL" \
    --out "$out" \
    --overwrite >/dev/null
}

# Initial sweep (decode anything present once)
shopt -s nullglob
for hg in "$SAVE_DIR"/save*.hg "$SAVE_DIR"/mf_save*.hg; do
  decode_one "$hg"
done

# Watch for changes
inotifywait -m -e close_write -e moved_to --format '%w%f' "$SAVE_DIR" \
  | while read -r path; do
      case "$(basename "$path")" in
        save*.hg|mf_save*.hg) decode_one "$path" ;;
        *) : ;;
      esac
    done
