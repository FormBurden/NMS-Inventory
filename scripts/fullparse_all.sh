#!/usr/bin/env bash
set -euo pipefail
python3 -m scripts.python.nms_fullparse -i storage/decoded/saveexpedition.json    -o output/fullparse/saveexpedition.full.json
python3 -m scripts.python.nms_fullparse -i storage/decoded/saveexpendition2.json  -o output/fullparse/saveexpendition2.full.json
python3 -m scripts.python.nms_fullparse -i storage/decoded/savenormal.json        -o output/fullparse/savenormal.full.json
python3 -m scripts.python.nms_fullparse -i storage/decoded/savenormal2.json       -o output/fullparse/savenormal2.full.json
cat > .nmsinventory-files.txt <<'LIST'
data/mappings/keys_map.json
output/fullparse/saveexpedition.full.json
output/fullparse/saveexpendition2.full.json
output/fullparse/savenormal.full.json
output/fullparse/savenormal2.full.json
LIST
bash scripts/collect_debug_bundle.sh --no-defaults --name edtb_fullparse_results_05 --from .nmsinventory-files.txt --no-logs --no-network
