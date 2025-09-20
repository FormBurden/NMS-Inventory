#!/usr/bin/env bash
# scripts/watch_saves.sh
# Drop-in replacement: avoids bulk-decoding old saves on startup.
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"   # scripts/ -> repo root
DOTENV="${REPO_ROOT}/.env"

# --- dotenv ---------------------------------------------------------------
if [[ -f "$DOTENV" ]]; then
  # shellcheck disable=SC1090
  source "$DOTENV"
fi

# Required: WATCH_SAVES_DIRS from .env
if [[ -z "${WATCH_SAVES_DIRS:-}" ]]; then
  echo "[ERR] WATCH_SAVES_DIRS not set in .env"
  exit 1
fi

# Optional knobs
WATCH_SAVES_SINCE_DAYS="${WATCH_SAVES_SINCE_DAYS:-30}"
WATCH_DECODE_ON_START="${WATCH_DECODE_ON_START:-1}"
OUT_DIR="${DECODE_OUT_DIR:-${REPO_ROOT}/.cache/decoded}"

# Decoder hint:
# - If NMSSAVETOOL points to a file, we call: python3 <file> <src> > out.json
# - Else we try bare 'nmssavetool <src> > out.json'
NMSSAVETOOL="${NMSSAVETOOL:-nmssavetool}"

mkdir -p "$OUT_DIR"

# Split WATCH_SAVES_DIRS on colon/comma/semicolon/space
readarray -t WATCH_DIRS < <(printf '%s\n' "$WATCH_SAVES_DIRS" | tr ';:,' '\n' | tr -s ' ' '\n' | sed '/^$/d')

decode_one() {
  local src="$1"
  local base name out tmp
  [[ -f "$src" ]] || return 0
  [[ "${src##*.}" == "hg" ]] || return 0

  base="$(basename -- "$src")"
  name="${base%.*}"
  out="${OUT_DIR}/${name}.json"
  tmp="${out}.tmp"

  echo "[decode] $src -> $out"

  if [[ -f "$NMSSAVETOOL" ]]; then
    # Treat as a python module file
    if ! python3 "$NMSSAVETOOL" "$src" > "$tmp" 2>/dev/null; then
      echo "[ERR] decode failed via python3 $NMSSAVETOOL"
      rm -f "$tmp"
      return 1
    fi
  else
    # Treat as a command on PATH
    if ! $NMSSAVETOOL "$src" > "$tmp" 2>/dev/null; then
      echo "[ERR] decode failed via $NMSSAVETOOL (PATH). Set NMSSAVETOOL in .env to point to nmssavetool.py or binary."
      rm -f "$tmp"
      return 1
    fi
  fi

  mv -f "$tmp" "$out"
  return 0
}

initial_pass() {
  local days="$1"
  local cutoff
  cutoff="$(date -d "${days} days ago" +%Y-%m-%d)"
  echo "[info] Initial pass: only files newer than ${cutoff} (${days} days)."

  for d in "${WATCH_DIRS[@]}"; do
    [[ -d "$d" ]] || { echo "[warn] Missing dir: $d"; continue; }
    # GNU find: -newermt supports the readable date form.
    while IFS= read -r -d '' f; do
      decode_one "$f"
    done < <(find "$d" -type f -name '*.hg' -newermt "$cutoff" -print0)
  done
}

watch_loop() {
  command -v inotifywait >/dev/null 2>&1 || {
    echo "[ERR] inotifywait not found. Install inotify-tools."
    exit 1
  }

  # Build inotify list
  local args=()
  for d in "${WATCH_DIRS[@]}"; do
    [[ -d "$d" ]] && args+=("$d")
  done
  [[ "${#args[@]}" -gt 0 ]] || {
    echo "[ERR] No valid directories to watch."
    exit 1
  }

  echo "[watch] Monitoring for new/updated *.hg files under:"
  printf '  - %s\n' "${args[@]}"

  inotifywait -m -e close_write,create,move --format '%w%f' "${args[@]}" | \
  while IFS= read -r path; do
    [[ "${path##*.}" == "hg" ]] || continue
    decode_one "$path"
  done
}

# --- run ------------------------------------------------------------------
if [[ "$WATCH_DECODE_ON_START" == "1" ]]; then
  initial_pass "$WATCH_SAVES_SINCE_DAYS"
else
  echo "[info] Skipping initial decode pass (WATCH_DECODE_ON_START=0)."
fi

watch_loop
