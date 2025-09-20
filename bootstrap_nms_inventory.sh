#!/usr/bin/env bash
set -euo pipefail

# Usage: bash bootstrap_nms_inventory.sh [ROOT_DIR]
ROOT="${1:-NMS-Inventory}"
echo "[*] Creating project at: $ROOT"

# --- folders
mkdir -p "$ROOT"/public/Inventory "$ROOT"/public/api \
         "$ROOT"/includes "$ROOT"/assets/css "$ROOT"/assets/js \
         "$ROOT"/storage/decoded "$ROOT"/storage/cleaned "$ROOT"/storage/icons "$ROOT"/storage/logs \
         "$ROOT"/scripts

# --- files (PASTE CONTENT where indicated) -------------------------------

cat > "$ROOT/.env.example" <<'ENV'
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=nms
DB_PASS=changeme
DB_NAME=nms
ENV

cat > "$ROOT/includes/bootstrap.php" <<'PHP'
<?php
// Very small bootstrap (EDTB-style, no framework)
$env = [];
$envPath = __DIR__ . '/../.env';
if (file_exists($envPath)) {
  foreach (file($envPath, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
    if (str_starts_with(trim($line), '#')) continue;
    if (!str_contains($line, '=')) continue;
    [$k, $v] = explode('=', $line, 2);
    $env[trim($k)] = trim($v);
  }
} else {
  // Fall back to .env.example
  foreach (file(__DIR__ . '/../.env.example', FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
    if (str_starts_with(trim($line), '#')) continue;
    if (!str_contains($line, '=')) continue;
    [$k, $v] = explode('=', $line, 2);
    $env[trim($k)] = trim($v);
  }
}

function env($k, $default=null) {
  global $env; return $env[$k] ?? $default;
}

require_once __DIR__ . '/db.php';
require_once __DIR__ . '/icon_map.php';
PHP

cat > "$ROOT/includes/db.php" <<'PHP'
<?php
function db(): PDO {
  static $pdo = null;
  if ($pdo) return $pdo;
  $dsn = sprintf('mysql:host=%s;port=%s;dbname=%s;charset=utf8mb4',
    env('DB_HOST','127.0.0.1'), env('DB_PORT','3306'), env('DB_NAME','nms'));
  $pdo = new PDO($dsn, env('DB_USER','nms'), env('DB_PASS',''), [
    PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
    PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
  ]);
  return $pdo;
}

/**
 * Returns current totals per resource_id.
 * Strategy:
 *  - Use latest snapshot_ts from INITIAL_TABLE as baseline
 *  - Sum amounts at that baseline
 *  - Add summed net from LEDGER_TABLE for sessions after that baseline
 */
function current_totals($includeTech=false): array {
  $pdo = db();
  $init = env('INITIAL_TABLE','nms_initial_items');
  $ledg = env('LEDGER_TABLE','nms_ledger_deltas');

  $baselineTs = $pdo->query("SELECT MAX(snapshot_ts) AS ts FROM `$init`")->fetchColumn();
  if (!$baselineTs) return [];

  $params = [':ts'=>$baselineTs];
  $techFilter = $includeTech ? "" : " AND resource_type <> 'Technology' ";

  $base = $pdo->prepare("SELECT resource_id, SUM(amount) AS amt
                         FROM `$init`
                         WHERE snapshot_ts = :ts $techFilter
                         GROUP BY resource_id");
  $base->execute($params);
  $baseMap = [];
  foreach ($base as $r) $baseMap[strtoupper($r['resource_id'])] = (int)$r['amt'];

  $led = $pdo->prepare("SELECT resource_id, SUM(net) AS net
                        FROM `$ledg`
                        WHERE session_end >= :ts
                        GROUP BY resource_id");
  $led->execute($params);
  foreach ($led as $r) {
    $k = strtoupper($r['resource_id']);
    $baseMap[$k] = ($baseMap[$k] ?? 0) + (int)$r['net'];
  }
  return $baseMap;
}
PHP

cat > "$ROOT/includes/icon_map.php" <<'PHP'
<?php
/**
 * External icon resolver (seed map + Fandom fallback).
 * Many product icons are available at:
 *   https://nomanssky.fandom.com/wiki/Category:Product_icons
 * We try an explicit map first; else try "Special:FilePath/<TOKEN>.png" where
 * <TOKEN> is often PRODUCT.X or Product.x depending on the asset. This won’t
 * be perfect for every id, but it gets us started and we can grow the map.
 */
function nms_icon_url(string $resourceId, string $resourceType=''): string {
  $RID = strtoupper($resourceId);

  // Seed known common items (expand as you encounter them)
  $seed = [
    'PRODUCT.ANTIMATTER'   => 'https://nomanssky.fandom.com/wiki/Special:FilePath/PRODUCT.ANTIMATTER.png',
    'PRODUCT.WARPCELL'     => 'https://nomanssky.fandom.com/wiki/Special:FilePath/PRODUCT.WARPCELL.png',
    'PRODUCT.METALPLATING' => 'https://nomanssky.fandom.com/wiki/Special:FilePath/Product.metalplating.png',
    'SUBSTANCE.CARBON'     => 'https://nomanssky.fandom.com/wiki/Special:FilePath/Substance.carbon.png',
    'SUBSTANCE.OXYGEN'     => 'https://nomanssky.fandom.com/wiki/Special:FilePath/Substance.oxygen.png',
    'SUBSTANCE.FERRITE_DUST'=> 'https://nomanssky.fandom.com/wiki/Special:FilePath/Ferrite_Dust_Icon.png',
    'SUBSTANCE.PURE_FERRITE'=> 'https://nomanssky.fandom.com/wiki/Special:FilePath/Pure_Ferrite_Icon.png',
    'SUBSTANCE.MAGNETISED_FERRITE'=> 'https://nomanssky.fandom.com/wiki/Special:FilePath/Magnetised_Ferrite_Icon.png',
  ];
  if (isset($seed[$RID])) return $seed[$RID];

  // Fallback heuristics: try a few URL shapes
  $candidates = [];

  // If resourceType known, try Product./Substance. prefixes
  if (stripos($resourceType, 'product') !== false && !str_starts_with($RID,'PRODUCT.')) {
    $candidates[] = "https://nomanssky.fandom.com/wiki/Special:FilePath/PRODUCT.$RID.png";
    $candidates[] = "https://nomanssky.fandom.com/wiki/Special:FilePath/Product.$RID.png";
  }
  if (stripos($resourceType, 'substance') !== false && !str_starts_with($RID,'SUBSTANCE.')) {
    $candidates[] = "https://nomanssky.fandom.com/wiki/Special:FilePath/SUBSTANCE.$RID.png";
    $candidates[] = "https://nomanssky.fandom.com/wiki/Special:FilePath/Substance.$RID.png";
  }

  // Last-ditch: use resourceId as file name
  $safe = preg_replace('/[^A-Z0-9._-]+/','_', $RID);
  $candidates[] = "https://nomanssky.fandom.com/wiki/Special:FilePath/$safe.png";

  // We don’t HEAD-check (to keep it snappy). First candidate wins.
  return $candidates[0];
}
PHP

cat > "$ROOT/public/index.php" <<'PHP'
<?php header('Location: /Inventory/'); exit;
PHP

cat > "$ROOT/public/Inventory/index.php" <<'PHP'
<?php require_once __DIR__ . '/../../includes/bootstrap.php'; ?>
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>NMS Inventory</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <link rel="stylesheet" href="/assets/css/app.css">
</head>
<body>
  <header class="topbar">
    <div class="title">NMS Inventory</div>
    <div class="actions">
      <label><input type="checkbox" id="includeTech"> Include Tech</label>
      <input type="text" id="search" placeholder="Search…">
    </div>
  </header>
  <main>
    <div id="grid" class="grid"></div>
  </main>
  <script>window.NMS_BASE="/";</script>
  <script src="/assets/js/inventory.js"></script>
</body>
</html>
PHP

cat > "$ROOT/public/api/inventory.php" <<'PHP'
<?php
require_once __DIR__ . '/../../includes/bootstrap.php';
header('Content-Type: application/json; charset=utf-8');

$includeTech = isset($_GET['include_tech']) && ($_GET['include_tech'] === '1' || strcasecmp($_GET['include_tech'],'true')===0);
$totals = current_totals($includeTech);

// shape rows for UI (id, amount, icon)
$out = [];
$pdo = db();
// Try to infer type from latest snapshot row (so icons can guess Product/Substance)
if (!empty($totals)) {
  $init = env('INITIAL_TABLE','nms_initial_items');
  $baselineTs = $pdo->query("SELECT MAX(snapshot_ts) FROM `$init`")->fetchColumn();
  $q = $pdo->prepare("SELECT resource_id, resource_type
                      FROM `$init` WHERE snapshot_ts = :ts GROUP BY resource_id, resource_type");
  $q->execute([':ts'=>$baselineTs]);
  $rtype = [];
  foreach ($q as $r) $rtype[strtoupper($r['resource_id'])] = $r['resource_type'];
  foreach ($totals as $rid => $amt) {
    $rt = $rtype[$rid] ?? '';
    $out[] = [
      'resource_id' => $rid,
      'amount' => (int)$amt,
      'icon_url' => nms_icon_url($rid, $rt),
      'type' => $rt
    ];
  }
}

echo json_encode(['ok'=>true,'rows'=>$out], JSON_UNESCAPED_SLASHES);
PHP

cat > "$ROOT/assets/css/app.css" <<'CSS'
:root { --bg:#0c1014; --fg:#dfe7ef; --muted:#9fb3c8; --card:#121820; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:14px/1.45 system-ui,Segoe UI,Roboto,Ubuntu; }
.topbar { display:flex; justify-content:space-between; align-items:center; padding:10px 14px; background:#0f141a; border-bottom:1px solid #1c2733;}
.title { font-weight:700; font-size:16px; }
.actions { display:flex; gap:12px; align-items:center; color:var(--muted); }
.actions input[type="text"]{ background:#0b0f14; color:var(--fg); border:1px solid #1c2733; padding:6px 8px; border-radius:6px; min-width:200px; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:10px; padding:14px; }
.card { background:var(--card); border:1px solid #1c2733; border-radius:12px; padding:10px; display:flex; gap:10px; align-items:center; box-shadow:0 2px 10px rgba(0,0,0,.2); }
.card .icon { width:42px; height:42px; flex:0 0 42px; border-radius:8px; background:#0b0f14; display:grid; place-items:center; overflow:hidden; }
.card .icon img { width:100%; height:100%; object-fit:contain; image-rendering:crisp-edges; }
.card .meta { flex:1; min-width:0; }
.card .rid { font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size:12px; color:#c3d1df; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.card .amt { font-weight:700; }
CSS

cat > "$ROOT/assets/js/inventory.js" <<'JS'
(function(){
  const grid = document.getElementById('grid');
  const search = document.getElementById('search');
  const includeTech = document.getElementById('includeTech');

  function el(tag, props={}, children=[]) {
    const e = document.createElement(tag);
    Object.assign(e, props);
    for (const c of children) e.appendChild(c);
    return e;
  }

  function cardRow(r) {
    const img = el('img', {src:r.icon_url, alt:r.resource_id, loading:'lazy'});
    return el('div', {className:'card'}, [
      el('div', {className:'icon'}, [img]),
      el('div', {className:'meta'}, [
        el('div', {className:'rid', title:r.resource_id, textContent:r.resource_id}),
        el('div', {className:'amt', textContent:r.amount.toLocaleString()}),
      ])
    ]);
  }

  let all = [];
  function render() {
    grid.innerHTML = '';
    const q = (search.value || '').trim().toUpperCase();
    const rows = q ? all.filter(r => r.resource_id.includes(q)) : all;
    for (const r of rows) grid.appendChild(cardRow(r));
  }

  async function load() {
    const params = new URLSearchParams();
    if (includeTech.checked) params.set('include_tech','1');
    const res = await fetch('/api/inventory.php?'+params.toString());
    const js = await res.json();
    all = js.rows || [];
    render();
  }

  search.addEventListener('input', render);
  includeTech.addEventListener('change', load);

  load();
})();
JS

cat > "$ROOT/scripts/run_pipeline.sh" <<'BASH'
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

: "${NMSSAVETOOL:=$(grep '^NMSSAVETOOL=' .env 2>/dev/null | cut -d= -f2-)}"
: "${NMS_HG_PATH:=$(grep '^NMS_HG_PATH=' .env 2>/dev/null | cut -d= -f2-)}"
: "${SESSION_MINUTES:=$(grep '^SESSION_MINUTES=' .env 2>/dev/null | cut -d= -f2-)}"
: "${USE_MTIME:=$(grep '^USE_MTIME=' .env 2>/dev/null | cut -d= -f2-)}"
: "${INITIAL_TABLE:=$(grep '^INITIAL_TABLE=' .env 2>/dev/null | cut -d= -f2-)}"
: "${LEDGER_TABLE:=$(grep '^LEDGER_TABLE=' .env 2>/dev/null | cut -d= -f2-)}"

DEC="$ROOT/storage/decoded"
CLEAN="$ROOT/storage/cleaned"
LOGS="$ROOT/storage/logs"

stamp="$(date +'%Y-%m-%d_%H-%M-%S')"
raw_json="$DEC/save_$stamp.json"
clean_json="$CLEAN/save_$stamp.cleaned.json"

echo "[PIPE] decoding -> $raw_json"
python3 "$NMSSAVETOOL" decompress "$NMS_HG_PATH" "$raw_json" >"$LOGS/nmssavetool.$stamp.log" 2>&1

echo "[PIPE] cleaning -> $clean_json"
python3 /mnt/data/nms_decode_clean.py --json "$raw_json" --out "$clean_json" \
  --print-summary >"$LOGS/nms_decode_clean.$stamp.log" 2>&1

# Initial import (stores a full baseline snapshot rowset)
echo "[PIPE] initial import into DB ($INITIAL_TABLE)"
python3 /mnt/data/nms_resource_ledger_v3.py --initial \
  --saves "$clean_json" \
  --db-import --db-env "$ROOT/.env" --db-table "$INITIAL_TABLE" \
  --use-mtime >"$LOGS/initial_import.$stamp.log" 2>&1

# Ledger: compare current JSON vs baseline in DB (latest snapshot)
# Writes session deltas into LEDGER_TABLE
echo "[PIPE] ledger compare (baseline=latest) -> $LEDGER_TABLE"
python3 /mnt/data/nms_resource_ledger_v3.py \
  --saves "$CLEAN" \
  --baseline-db-table "$INITIAL_TABLE" \
  --baseline-snapshot latest \
  --db-write-ledger --db-env "$ROOT/.env" --db-ledger-table "$LEDGER_TABLE" \
  --session-minutes "${SESSION_MINUTES:-15}" \
  ${USE_MTIME:+--use-mtime} >"$LOGS/ledger.$stamp.log" 2>&1

echo "[PIPE] done."
BASH

cat > "$ROOT/scripts/watch_saves.sh" <<'BASH'
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

: "${NMS_HG_PATH:=$(grep '^NMS_HG_PATH=' .env 2>/dev/null | cut -d= -f2-)}"
if [[ -z "${NMS_HG_PATH:-}" ]]; then
  echo "[ERR] NMS_HG_PATH not set in .env"
  exit 1
fi

echo "[WATCH] monitoring $NMS_HG_PATH"
echo "[WATCH] requires inotifywait (inotify-tools). Ctrl+C to stop."

# Run once at start (so UI isn't empty)
bash "$ROOT/scripts/run_pipeline.sh" || true

if command -v inotifywait >/dev/null 2>&1; then
  while inotifywait -e close_write,modify,move,attrib "$NMS_HG_PATH"; do
    echo "[WATCH] change detected -> pipeline"
    bash "$ROOT/scripts/run_pipeline.sh" || true
  done
else
  echo "[WARN] inotifywait not found; polling every 15s"
  prev=""
  while true; do
    cur="$(stat -c %Y "$NMS_HG_PATH" 2>/dev/null || echo 0)"
    if [[ "$cur" != "$prev" ]]; then
      prev="$cur"
      echo "[WATCH] change detected (poll) -> pipeline"
      bash "$ROOT/scripts/run_pipeline.sh" || true
    fi
    sleep 15
  done
fi
BASH

cat > "$ROOT/scripts/collect_debug_bundle.sh" <<'BASH'
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
BASH

cat > "$ROOT/README.md" <<'MD'
# NMS-Inventory

A small PHP UI + background pipeline that:
- watches your No Man’s Sky save (.hg),
- decodes -> cleans -> imports inventory snapshots,
- computes session ledger deltas,
- serves a simple UI showing current inventory with external icons.
MD

# --- permissions & finishing touches
chmod +x "$ROOT"/scripts/*.sh || true

echo "[*] Done."
echo "Next:"
echo "  1) cp \"$ROOT/.env.example\" \"$ROOT/.env\" && edit it"
echo "  2) php -S localhost:8080 -t \"$ROOT/public\""
echo "  3) bash \"$ROOT/scripts/watch_saves.sh\""
