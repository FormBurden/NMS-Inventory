#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   bash scripts/fetch_assistant_data.sh                # fetch latest
#   bash scripts/fetch_assistant_data.sh 6.1.4990       # or pin a version

PKG_ID="assistantapps.nomanssky.info"
NUGET="https://api.nuget.org/v3-flatcontainer/${PKG_ID}"
VER="${1:-}"

require() { command -v "$1" >/dev/null 2>&1 || { echo "Missing dependency: $1"; exit 2; }; }

require curl
require unzip

# jq is optional; if missing, fall back to a tiny Python parser
if ! command -v jq >/dev/null 2>&1; then
  if command -v python3 >/dev/null 2>&1; then
    JQLESS='python3 - <<PY
import json,sys
d=json.load(sys.stdin)
print(d["versions"][-1])
PY'
  else
    echo "NOTE: jq not found and no python3 available; please install jq (pacman -S jq)"; exit 2
  fi
fi

if [[ -z "${VER}" ]]; then
  echo "Discovering latest ${PKG_ID} version from NuGet…"
  if command -v jq >/dev/null 2>&1; then
    VER="$(curl -fsSL "${NUGET}/index.json" | jq -r '.versions[-1]')"
  else
    VER="$(curl -fsSL "${NUGET}/index.json" | bash -c "$JQLESS")"
  fi
fi

[[ -n "${VER}" ]] || { echo "Could not determine version"; exit 1; }

echo "Using version: ${VER}"
mkdir -p .cache/aa
cd .cache/aa

NUPKG="${PKG_ID}.${VER}.nupkg"
URL="${NUGET}/${VER}/${NUPKG}"

echo "Downloading: ${URL}"
curl -fsSL -o aa.nupkg "${URL}"

echo "Extracting to .cache/aa/pkg"
rm -rf pkg && mkdir -p pkg
unzip -oq "$(ls -1 .cache/aa/*.nupkg | head -n1)" \
  'contentFiles/any/any/Assets/data/*' \
  'contentFiles/any/any/Assets/json/en-us/*' \
  -d .cache/aa/pkg


echo "Found JSON files under Assets/:"
find pkg -type f -path "*/Assets/*" -name '*.json' -print | sed 's#^.*/Assets/#  Assets/#'

echo "OK."
