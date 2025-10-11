#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

NAME="${1:-nms_inventory_debug}"
OUT="bundle_${NAME}_$(date +'%Y%m%d_%H%M%S').tar.gz"

# Default files to include (adjust as needed)
cat > .edtb-files.txt <<'LIST'
.env
.env.example
public/Inventory/index.php
public/api/inventory.php
includes/bootstrap.php
includes/db.php
includes/icon_map.php
assets/css/app.css
assets/js/inventory.js
scripts/run_pipeline.sh
scripts/watch_saves.sh
scripts/collect_debug_bundle.sh
storage/logs/
LIST

tar -czf "$OUT" --files-from .edtb-files.txt

echo "bundle: $OUT"
sha256sum "$OUT" | awk '{print "bundle checksum: "$1}'
echo "SOURCES: files"
echo "notes: | Reference bundle for NMS-Inventory."

# Repros / curls (kept AFTER the bundle per your preference)
echo
echo "# Hit the API"
echo "curl -sS 'http://localhost:8080/api/inventory.php' | jq | head -100"
