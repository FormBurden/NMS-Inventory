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
curl -fsSL -o "${NUPKG}" "${URL}"

echo "Extracting to .cache/aa/pkg"
rm -rf pkg && mkdir -p pkg
unzip -oq "${NUPKG}" \
  'contentFiles/any/any/Assets/data/*' \
  'contentFiles/any/any/Assets/json/en-us/*' \
  'contentFiles/any/any/Assets/json/en/*' \
  'Assets/data/*' \
  'Assets/json/en-us/*' \
  'Assets/json/en/*' \
  -d pkg



echo "Found JSON files under Assets/:"
find pkg -type f -path "*/Assets/*" -name '*.json' -print | sed 's#^.*/Assets/#  Assets/#'

echo "OK."

# --- CDN icon presence index ---------------------------------------------------
build_cdn_icon_index() {
  local BASE="https://cdn.nmsassistant.com"
  # Known icon folders on the CDN root
  local CATS=(products rawMaterials tradeItems curiosities other constructedTechnology upgradeModules technology building proceduralProducts cooking)

  echo "Building CDN icon index from ${BASE}/..."
  : > cdn_icon_index.json
  printf '{"base":"%s","generated":"%s","categories":{}}' \
    "$BASE" "$(date -u +%FT%TZ)" > cdn_icon_index.json

  # ---- Online mode: crawl the CDN directory indexes (fast path) ----
  if command -v jq >/dev/null 2>&1; then
    for cat in "${CATS[@]}"; do
      echo "  - indexing: $cat"
      html="$(curl -fsSL "${BASE}/${cat}/" || true)"
      ids_json="$(
        printf '%s\n' "$html" \
        | grep -oE '[0-9]+\.png' \
        | sed 's/\.png$//' \
        | sort -n | uniq \
        | jq -R . | jq -s 'map(tonumber)'
      )"
      [[ -z "$ids_json" ]] && ids_json='[]'
      jq --arg cat "$cat" --argjson arr "$ids_json" \
         '.categories[$cat] = $arr' \
         cdn_icon_index.json > cdn_icon_index.json.tmp && mv cdn_icon_index.json.tmp cdn_icon_index.json
    done

  elif command -v python3 >/dev/null 2>&1; then
    python3 - <<'PY'
import json, re, subprocess, datetime, sys
BASE="https://cdn.nmsassistant.com"
CATS=["products","rawMaterials","tradeItems","curiosities","other","constructedTechnology","upgradeModules","technology","building","proceduralProducts","cooking"]
out={"base":BASE,"generated":datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),"categories":{}}
for cat in CATS:
    try:
        html = subprocess.check_output(["curl","-fsSL", f"{BASE}/{cat}/"], text=True)
    except subprocess.CalledProcessError:
        html = ""
    ids = sorted({int(m) for m in re.findall(r'([0-9]+)\.png', html)})
    out["categories"][cat] = ids
with open("cdn_icon_index.json","w") as f:
    json.dump(out, f)
print("CDN icon index written to .cache/aa/cdn_icon_index.json", file=sys.stderr)
PY
  fi

  # ---- Offline fallback: derive from items_local.json if crawl produced nothing ----
  # We're still in .cache/aa (see earlier cd), so items file is ../../public/data/items_local.json
  local ITEMS_REL='../../public/data/items_local.json'
  local nonempty="0"
  if command -v jq >/dev/null 2>&1; then
    if [[ -s cdn_icon_index.json ]]; then
      nonempty="$(jq -r '(.categories // {}) | [ .[] | length ] | add // 0' cdn_icon_index.json 2>/dev/null || echo 0)"
    fi
  fi
  if [[ ! -s cdn_icon_index.json || "${nonempty}" == "0" ]]; then
    echo "CDN crawl empty/unavailable; building index from ${ITEMS_REL}"
    if [[ -f "${ITEMS_REL}" ]]; then
      if command -v python3 >/dev/null 2>&1; then
        python3 - <<'PY'
import json, re, sys, os, datetime
p='../../public/data/items_local.json'
try:
    with open(p,'r') as f:
        items=json.load(f)
except Exception:
    items={}
cats={}
for _,v in (items or {}).items():
    icon=v.get('icon')
    if not isinstance(icon,str): continue
    m=re.search(r'cdn\.nmsassistant\.com/([^/]+)/([0-9]+)\.png', icon)
    if not m: continue
    cat=m.group(1); id=int(m.group(2))
    cats.setdefault(cat, set()).add(id)
out={"base":"https://cdn.nmsassistant.com","generated":datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),"categories":{k:sorted(list(s)) for k,s in cats.items()}}
with open("cdn_icon_index.json","w") as f: json.dump(out,f)
print("CDN icon index (offline from items_local.json) written to .cache/aa/cdn_icon_index.json", file=sys.stderr)
PY
      elif command -v php >/dev/null 2>&1; then
        # PHP fallback (no jq/python3 needed): derive from items_local.json
        php -r '$p="../../public/data/items_local.json";
        $i=@json_decode(@file_get_contents($p),true)?:[];
        $cats=[];
        foreach($i as $row){
          $icon=$row["icon"]??"";
          if(is_string($icon) && preg_match("~cdn\\.nmsassistant\\.com/([^/]+)/([0-9]+)\\.png~",$icon,$m)){
            $cats[$m[1]][]=(int)$m[2];
          }
        }
        foreach($cats as &$a){ $a=array_values(array_unique($a)); sort($a); }
        $out=["base"=>"https://cdn.nmsassistant.com","generated"=>gmdate("c"),"categories"=>$cats];
        file_put_contents("cdn_icon_index.json", json_encode($out));'
      else
        echo "NOTE: offline fallback needs python3 or php; skipping."
      fi
    else
      echo "NOTE: ${ITEMS_REL} not found; cannot build offline CDN index."
    fi
  fi

  if [[ -s cdn_icon_index.json ]]; then
    echo "CDN icon index ready: $(pwd)/cdn_icon_index.json"
  else
    echo "WARNING: cdn_icon_index.json not created; writing minimal skeleton." ; printf '{"base":"%s","generated":"%s","categories":{}}' "$BASE" "$(date -u +%FT%TZ)" > cdn_icon_index.json
  fi
}

build_cdn_icon_index
# -------------------------------------------------------------------------------
