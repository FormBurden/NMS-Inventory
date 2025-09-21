<?php
declare(strict_types=1);

/**
 * Inventory API
 *  - GET /api/inventory.php
 *    ?scope=character|base|storage|frigate|corvette|ship|vehicles
 *    &include_tech=0|1
 *    &root=<save_root>         (optional: force a single root)
 *    &source=active|latest|all (optional: choose snapshot source; default=all)
 *
 * Unscoped: uses v_api_inventory_rows_active_combined (fast combined view)
 * Scoped:   aggregates from nms_items limited to snapshots determined by `source`
 */

require_once __DIR__ . '/../../includes/db.php';
require_once __DIR__ . '/../../includes/bootstrap.php';

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

function json_out($data, int $code = 200): void {
  http_response_code($code);
  echo json_encode($data, JSON_UNESCAPED_SLASHES);
  exit;
}

try {
  $pdo = db(); // PDO with ERRMODE_EXCEPTION expected

  // Inputs
  $scope       = isset($_GET['scope']) ? strtolower(trim((string)$_GET['scope'])) : '';
  $includeTech = (isset($_GET['include_tech']) && $_GET['include_tech'] === '1');
  $root        = isset($_GET['root']) ? trim((string)$_GET['root']) : '';
  $source      = isset($_GET['source']) ? strtolower(trim((string)$_GET['source'])) : 'all'; // active|latest|all

  if ($root !== '' && !preg_match('/^[A-Za-z0-9_.-]+$/', $root)) {
    json_out(['ok'=>false,'error'=>'Invalid root'], 400);
  }
  if (!in_array($source, ['active','latest','all'], true)) $source = 'all';

  // Unscoped -> combined view (fast path)
  if ($scope === '') {
    $rows = [];
    $sql = "SELECT resource_id, amount, item_type FROM v_api_inventory_rows_active_combined";
    foreach ($pdo->query($sql) as $r) {
      $rid = (string)$r['resource_id'];
      $rows[] = [
        'resource_id' => $rid,
        'amount'      => (int)$r['amount'],
        'type'        => (string)$r['item_type'],
        'icon_url'    => "/api/icon.php?id=" . rawurlencode($rid) . "&type=" . rawurlencode((string)$r['item_type']),
      ];
    }
    json_out(['ok'=>true, 'rows'=>$rows]);
  }

  // Supported scopes
  $validScopes = ['character','base','storage','frigate','corvette','ship','vehicles'];
  if (!in_array($scope, $validScopes, true)) {
    json_out(['ok'=>false,'error'=>'Unsupported scope'], 400);
  }

  // Map logical scopes to owner_type prefixes seen in your DB
  $scopeOwners = [
    'character' => ['SUIT','EXOSUIT','CHAR','CHARACTER','PLAYER'],
    'base'      => [], // handled by resource_id prefixes instead (see below)
    'storage'   => ['STORAGE','CONTAINER'],
    'frigate'   => ['FRIGATE'], // may be empty (ok)
    'corvette'  => ['FREIGHTER','CORVETTE','CAPITAL','CAPSHIP'], // your DB uses FREIGHTER
    'ship'      => ['SHIP','STARSHIP','UNKNOWN'], // UNKNOWN is your largest bucket
    'vehicles'  => ['VEHICLE','EXOCRAFT','EXO_CRAFT','VEHICLES'],
  ];
  $owners = $scopeOwners[$scope] ?? [];

  // Choose snapshots:
  // root=...       -> latest for that root only
  // source=active  -> latest per active root
  // source=latest  -> single latest overall
  // source=all     -> union(active_latest ∪ latest_overall)  [DEFAULT]
  $snapIds = [];

  if ($root !== '') {
    $q = $pdo->prepare("SELECT snapshot_id FROM v_latest_snapshot_by_root WHERE save_root = :root");
    $q->execute([':root'=>$root]);
    $sid = $q->fetchColumn();
    if ($sid) $snapIds[] = (int)$sid;
  } else {
    if ($source === 'active' || $source === 'all') {
      $sql = "SELECT v.snapshot_id
              FROM v_latest_snapshot_by_root v
              JOIN nms_save_roots r ON r.save_root = v.save_root
              WHERE r.is_active = 1";
      foreach ($pdo->query($sql) as $r) $snapIds[] = (int)$r['snapshot_id'];
    }
    if ($source === 'latest' || $source === 'all') {
      $sid = $pdo->query("SELECT snapshot_id FROM nms_snapshots ORDER BY imported_at DESC, snapshot_id DESC LIMIT 1")->fetchColumn();
      if ($sid) $snapIds[] = (int)$sid;
    }
  }

  // Deduplicate
  $snapIds = array_values(array_unique(array_map('intval', $snapIds)));

  // Final fallback: if still empty, try latest overall
  if (!$snapIds) {
    $sid = $pdo->query("SELECT snapshot_id FROM nms_snapshots ORDER BY imported_at DESC, snapshot_id DESC LIMIT 1")->fetchColumn();
    if ($sid) $snapIds[] = (int)$sid;
  }
  if (!$snapIds) json_out(['ok'=>true,'rows'=>[]]);

  // Bind snapshot placeholders
  $ph = []; $bind = [];
  foreach ($snapIds as $i => $sid) { $k=":sid$i"; $ph[]=$k; $bind[$k]=$sid; }

  // Owner-type LIKEs (unless scope=base, which relies on resource_id prefixes)
  $likeSql = [];
  foreach ($owners as $i => $o) {
    $k=":own$i";
    $likeSql[]="UPPER(TRIM(owner_type)) LIKE $k";
    $bind[$k]=strtoupper($o).'%';
  }
  $ownerSql = $owners ? " AND (".implode(' OR ', $likeSql).")" : "";

  // Include-Tech filter (skip TECHONLY unless explicitly requested)
  $techSql = $includeTech ? "" : " AND UPPER(inventory) <> 'TECHONLY' ";

  // Base/build prefixes (used to include/exclude)
  $basePrefixes = ['B_', 'BUILD_', 'BASE_', 'BP_']; // covers B_*, BUILD_*, BASE_*, BP_*
  $ridInclude = "";
  $ridExclude = "";

  if ($scope === 'base') {
    $ors = [];
    foreach ($basePrefixes as $i => $p) { $k=":bp$i"; $ors[]="resource_id LIKE $k"; $bind[$k]=$p.'%'; }
    $ridInclude = $ors ? " AND (".implode(' OR ', $ors).")" : "";
  } elseif ($scope === 'ship') {
    // When ship scope includes UNKNOWN owner_type, avoid showing obvious base/build items
    $ands = [];
    foreach ($basePrefixes as $i => $p) { $k=":nbp$i"; $ands[]="resource_id NOT LIKE $k"; $bind[$k]=$p.'%'; }
    $ridExclude = $ands ? " AND ".implode(' AND ', $ands) : "";
  }

  // Final query
  $sql = "SELECT resource_id, SUM(amount) AS amount, MIN(item_type) AS item_type
          FROM nms_items
          WHERE snapshot_id IN (".implode(',', $ph).")
            $techSql
            $ownerSql
            $ridInclude
            $ridExclude
          GROUP BY resource_id";

  $stmt = $pdo->prepare($sql);
  $stmt->execute($bind);

  $rows = [];
  while ($r = $stmt->fetch()) {
    $rid = (string)$r['resource_id'];
    $rows[] = [
      'resource_id' => $rid,
      'amount'      => (int)$r['amount'],
      'type'        => (string)$r['item_type'],
      'icon_url'    => "/api/icon.php?id=" . rawurlencode($rid) . "&type=" . rawurlencode((string)$r['item_type']),
    ];
  }

  // If still empty for this scope, as a last resort try single latest overall only
  if (!$rows && count($snapIds) > 1) {
    $sid = $pdo->query("SELECT snapshot_id FROM nms_snapshots ORDER BY imported_at DESC, snapshot_id DESC LIMIT 1")->fetchColumn();
    if ($sid) {
      $stmt = $pdo->prepare(str_replace("snapshot_id IN (".implode(',', $ph).")", "snapshot_id = :latest_sid", $sql));
      $bind2 = $bind; // copy
      $bind2[':latest_sid'] = (int)$sid;
      // Strip old :sid* binds
      foreach (array_keys($bind2) as $k) if (preg_match('/^:sid\d+$/', $k)) unset($bind2[$k]);

      $stmt->execute($bind2);
      $rows = [];
      while ($r = $stmt->fetch()) {
        $rid = (string)$r['resource_id'];
        $rows[] = [
          'resource_id' => $rid,
          'amount'      => (int)$r['amount'],
          'type'        => (string)$r['item_type'],
          'icon_url'    => "/api/icon.php?id=" . rawurlencode($rid) . "&type=" . rawurlencode((string)$r['item_type']),
        ];
      }
    }
  }

  json_out(['ok'=>true, 'rows'=>$rows]);
} catch (Throwable $e) {
  error_log("[api/inventory.php] ".$e->getMessage());
  json_out(['ok'=>false,'error'=>'Internal error'], 500);
}
