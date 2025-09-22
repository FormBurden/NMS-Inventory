#!/usr/bin/env bash
set -euo pipefail

run() {
  local IN="$1"; local OUT="$2"
  if [[ -f "$IN" ]]; then
    echo "[run] $IN -> $OUT"
    python3 -m scripts.python.nms_fullparse -i "$IN" -o "$OUT"
  else
    echo "[skip] missing: $IN"
  fi
}

run storage/decoded/save.json               output/fullparse/save.full.json
run storage/decoded/save2.json              output/fullparse/save2.full.json
run storage/decoded/saveexpedition.json     output/fullparse/saveexpedition.full.json
run storage/decoded/saveexpendition2.json   output/fullparse/saveexpendition2.full.json
run storage/decoded/savenormal.json         output/fullparse/savenormal.full.json
run storage/decoded/savenormal2.json        output/fullparse/savenormal2.full.json
