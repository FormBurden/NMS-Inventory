#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

run_one() {
  local IN="$1"
  local stem="${IN##*/}"
  stem="${stem%.json}"
  local OUT="output/fullparse/${stem}.full.json"
  echo "[run] $IN -> $OUT"
  python3 -m scripts.python.nms_fullparse -i "$IN" -o "$OUT"
}

shopt -s nullglob
found=0
for IN in storage/decoded/*.json; do
  # ignore the manifest file if present
  [[ "$(basename "$IN")" == "_manifest_recent.json" ]] && continue
  run_one "$IN"
  found=1
done

if [[ $found -eq 0 ]]; then
  # stay quiet about “missing” specific mode files; just one informative line
  echo "[info] no decoded saves found under storage/decoded/"
fi
