#!/usr/bin/env bash
# watch_saves.sh — watch No Man's Sky save directories and (optionally) decode on changes
# Reads config from .env at the repo root.
#
# Env keys (set these in .env):
#   WATCH_SAVES_DIRS      = one or more directories (comma or colon separated)
#   WATCH_REGEX           = (optional) regex of files to react to (default matches *.hg, save.hg, mf_*)
#   WATCH_DEBOUNCE_SEC    = (optional) debounce per-dir in seconds (default 2)
#   WATCH_INITIAL_DECODE  = (optional) "true"|"false" — run a decode once at start (default true)
#
# Decoder selection (pick ONE approach below, highest priority that is set/available is used):
#   DECODE_CMD            = exact shell command to run; use __INPUT__ (file path) and __DIR__ (containing dir) placeholders
#                           Example: DECODE_CMD='python3 /path/nmssavetool.py "__DIR__"'
#   NMS_ST_CMD            = command template for nmssavetool; use __DIR__ placeholder
#                           Example: NMS_ST_CMD='python3 /mnt/NMS-Save-Decoder-main/nmssavetool.py "__DIR__"'
#   NMSSAVETOOL_PY        = path to nmssavetool.py; will run: python3 "$NMSSAVETOOL_PY" "__DIR__"
#   (legacy fallback)     = scripts/nms_decode_clean.py will be used if present and nothing else is configured
#
# Notes:
# - Works with inotifywait (preferred), fswatch, or a portable polling fallback.
# - If no decoder is configured, the watcher will still run and log file changes.

set -Eeuo pipefail

# ---------- util ----------
ts() { date +"%Y-%m-%d %H:%M:%S"; }
log() { printf "[%s] %s\n" "$(ts)" "$*"; }
die() { log "[ERR] $*"; exit 1; }

# ---------- locate repo root & load .env ----------
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
cd "$ROOT_DIR"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$ROOT_DIR/.env"
  set +a
fi

# ---------- collect watch dirs from WATCH_SAVES_DIRS ----------
# Accept comma, colon, or newline separated
WATCH_SAVES_DIRS="${WATCH_SAVES_DIRS:-}"
if [[ -z "$WATCH_SAVES_DIRS" ]]; then
  die "No watch directories configured.
Add WATCH_SAVES_DIRS to $ROOT_DIR/.env (comma- or colon-separated).
Example:
  WATCH_SAVES_DIRS=\"/mnt/Unlimited-Gaming/Modding/No-Mans-Sky/Saves/Saves,$HOME/.local/share/HelloGames/NMS\""
fi

# Normalize separators to commas
_dirs="${WATCH_SAVES_DIRS//$'\n'/,}"
_dirs="${_dirs//:/,}"

# Build WATCH_DIRS array; trim whitespace and skip missing dirs with a warning
IFS=',' read -r -a WATCH_DIRS <<< "$_dirs"
_tmp=()
for d in "${WATCH_DIRS[@]}"; do
  d="${d#"${d%%[![:space:]]*}"}"   # ltrim
  d="${d%"${d##*[![:space:]]}"}"   # rtrim
  [[ -z "$d" ]] && continue
  if [[ ! -d "$d" ]]; then
    log "[WARN] WATCH_SAVES_DIRS path not found: $d"
    continue
  fi
  _tmp+=("$d")
done
WATCH_DIRS=("${_tmp[@]}")

[[ ${#WATCH_DIRS[@]} -gt 0 ]] || die "No valid watch directories after filtering."

# ---------- config defaults ----------
WATCH_REGEX="${WATCH_REGEX:-(^|/)(save\.hg|.*\.hg|mf_.*|slot.*|save)$}"
WATCH_DEBOUNCE_SEC="${WATCH_DEBOUNCE_SEC:-2}"
WATCH_INITIAL_DECODE="${WATCH_INITIAL_DECODE:-true}"

# ---------- choose watcher backend ----------
BACKEND="poll"
if command -v inotifywait >/dev/null 2>&1; then
  BACKEND="inotify"
elif command -v fswatch >/dev/null 2>&1; then
  BACKEND="fswatch"
fi

# ---------- decoder command resolution ----------
resolve_decode_cmd() {
  # $1=input file (may be a directory hint), $2=dir containing the file
  local input="$1" dir="$2" cmd=""

  if [[ -n "${DECODE_CMD:-}" ]]; then
    cmd="${DECODE_CMD//__INPUT__/$input}"
    cmd="${cmd//__DIR__/$dir}"
    printf "%s" "$cmd"
    return 0
  fi

  if [[ -n "${NMS_ST_CMD:-}" ]]; then
    cmd="${NMS_ST_CMD//__DIR__/$dir}"
    printf "%s" "$cmd"
    return 0
  fi

  if [[ -n "${NMSSAVETOOL_PY:-}" && -f "$NMSSAVETOOL_PY" ]]; then
    printf 'python3 "%s" "%s"' "$NMSSAVETOOL_PY" "$dir"
    return 0
  fi

  if [[ -f "$ROOT_DIR/../NMS-Save-Decoder-main/nmssavetool.py" ]]; then
    printf 'python3 "%s" "%s"' "$ROOT_DIR/../NMS-Save-Decoder-main/nmssavetool.py" "$dir"
    return 0
  fi

  if [[ -f "$ROOT_DIR/scripts/nms_decode_clean.py" ]]; then
    # Legacy: expects a file input
    printf 'python3 "%s" "%s"' "$ROOT_DIR/scripts/nms_decode_clean.py" "$input"
    return 0
  fi

  # No decoder configured
  printf ""
}

run_decode() {
  local input="$1" dir="$2"
  local cmd
  cmd="$(resolve_decode_cmd "$input" "$dir")" || cmd=""
  if [[ -z "$cmd" ]]; then
    log "[dev] No decoder configured. Change detected at: $input"
    log "      Set DECODE_CMD, NMS_ST_CMD, or NMSSAVETOOL_PY in .env to enable decoding."
    return 0
  fi

  log "[dev] decode → $cmd"
  if ! eval "$cmd"; then
    log "[ERR] decode failed for: $input"
    return 1
  fi
  return 0
}

# ---------- debounce per directory ----------
declare -A __LAST_RUN=()
debounced_decode() {
  local input="$1" dir="$2" now last
  now="$(date +%s)"
  last="${__LAST_RUN[$dir]:-0}"

  if (( now - last < WATCH_DEBOUNCE_SEC )); then
    # Within debounce window; skip
    return 0
  fi
  __LAST_RUN[$dir]="$now"
  run_decode "$input" "$dir" || true
}

# ---------- backends ----------
watch_inotify() {
  # shellcheck disable=SC2046
  inotifywait -m -r \
    -e modify -e close_write -e moved_to -e create \
    --format '%w%f' \
    -- "${WATCH_DIRS[@]}" |
  while IFS= read -r path; do
    if [[ "$path" =~ $WATCH_REGEX ]]; then
      debounced_decode "$path" "$(dirname "$path")"
    fi
  done
}

watch_fswatch() {
  # fswatch outputs paths line-by-line
  fswatch -0 -r "${WATCH_DIRS[@]}" | while IFS= read -r -d '' path; do
    if [[ "$path" =~ $WATCH_REGEX ]]; then
      debounced_decode "$path" "$(dirname "$path")"
    fi
  done
}

watch_poll() {
  # Portable polling: compute a cheap per-dir change token and compare
  declare -A TOKENS=()
  while true; do
    for d in "${WATCH_DIRS[@]}"; do
      # Find newest mtime among files matching the regex candidates
      # (Approximation: check *.hg and mf_* to keep this light.)
      local newest
      newest="$(find "$d" -type f \( -name '*.hg' -o -name 'mf_*' -o -name 'save' -o -name 'save.hg' \) -printf '%T@\n' 2>/dev/null | sort -nr | head -n1 || true)"
      newest="${newest:-0}"
      if [[ "${TOKENS[$d]:-}" != "$newest" ]]; then
        TOKENS[$d]="$newest"
        # Pass a representative input path if we can find one; else just the dir
        local any
        any="$(find "$d" -type f \( -name '*.hg' -o -name 'mf_*' -o -name 'save' -o -name 'save.hg' \) -print -quit 2>/dev/null || true)"
        any="${any:-$d}"
        debounced_decode "$any" "$d"
      fi
    done
    sleep 1
  done
}

# ---------- initial decode (optional) ----------
if [[ "$WATCH_INITIAL_DECODE" == "true" ]]; then
  for d in "${WATCH_DIRS[@]}"; do
    # Try a typical save file name first, then fallback to the dir
    cand=""
    for n in "save.hg" "save" ; do
      [[ -f "$d/$n" ]] && { cand="$d/$n"; break; }
    done
    cand="${cand:-$d}"
    run_decode "$cand" "$d" || true
  done
fi

# ---------- banner & go ----------
log "[dev] watching ${#WATCH_DIRS[@]} save dir(s) with backend: $BACKEND"
for d in "${WATCH_DIRS[@]}"; do
  log "[dev]   • $d"
done

case "$BACKEND" in
  inotify) watch_inotify ;;
  fswatch) watch_fswatch ;;
  *)       log "[WARN] inotifywait/fswatch not found; using portable polling."; watch_poll ;;
esac
