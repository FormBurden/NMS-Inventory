<?php
declare(strict_types=1);

/**
 * Inventory API
 *  - GET /api/inventory.php
 *    ?scope=character|base|storage|frigate|corvette|ship|vehicles
 *    &include_tech=0|1
 *    &root=<save_root> (optional)
 *
 * Unscoped: uses v_api_inventory_rows_active_combined (fast combined view)
 * Scoped:   aggregates from nms_items limited to the latest snapshot per active root
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
  if ($root !== '' && !preg_match('/^[A-Za-z0-9_.-]+$/', $root)) {
    json_out(['ok'=>false,'error'=>'Invalid root'], 400);
  }

  // Unscoped → use your combined view
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

  // Map logical scopes to owner_type prefixes seen in your DB
  $scopeOwners = [
    'character' => ['SUIT','EXOSUIT','CHAR','CHARACTER','PLAYER'],
    'base'      => [], // handled by resource_id prefixes instead (see below)
    'storage'   => ['STORAGE','CONTAINER'],
    'frigate'   => ['FRIGATE'], // may be empty until you have data
    'corvette'  => ['FREIGHTER','CORVETTE','CAPITAL','CAPSHIP'],
    'ship'      => ['SHIP','STARSHIP','UNKNOWN'], // UNKNOWN is your largest bucket
    'vehicles'  => ['VEHICLE','EXOCRAFT','EXO_CRAFT','VEHICLES'],
  ];
  $owners = $scopeOwners[$scope] ?? [];
  if (!in_array($scope, ['base','character','storage','frigate','corvette','ship','vehicles'], true)) {
    json_out(['ok'=>false,'error'=>'Unsupported scope'], 400);
  }

  // Snapshot set: latest per active root (or a specific root if requested)
  $snapIds = [];
  if ($root !== '') {
    $q = $pdo->prepare("SELECT snapshot_id FROM v_latest_snapshot_by_root WHERE save_root = :root");
    $q->execute([':root'=>$root]);
    $sid = $q->fetchColumn();
    if ($sid) $snapIds[] = (int)$sid;
  } else {
    $sql = "SELECT v.snapshot_id
            FROM v_latest_snapshot_by_root v
            JOIN nms_save_roots r ON r.save_root = v.save_root
            WHERE r.is_active = 1";
    foreach ($pdo->query($sql) as $r) $snapIds[] = (int)$r['snapshot_id'];
  }
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
  foreach ($owners as $i => $o) { $k=":own$i"; $likeSql[]="UPPER(owner_type) LIKE $k"; $bind[$k]=strtoupper($o).'%'; }
  $ownerSql = $owners ? " AND (".implode(' OR ', $likeSql).")" : "";

  // Include-Tech filter (skip TECHONLY unless explicitly requested)
  $techSql = $includeTech ? "" : " AND UPPER(inventory) <> 'TECHONLY' ";

  // Base/build prefixes (used to include/exclude)
  $basePrefixes = ['B_', 'BUILD_', 'BASE_', 'BP_']; // covers your B_*, BUILD_*, BASE_*, BP_SALVAGE, etc.

  // Build resource_id include/exclude clauses
  $ridInclude = "";
  $ridExclude = "";
  if ($scope === 'base') {
    $ors = [];
    foreach ($basePrefixes as $i => $p) { $k=":bp$i"; $ors[]="resource_id LIKE $k"; $bind[$k]=$p.'%'; }
    $ridInclude = " AND (".implode(' OR ', $ors).")";
  } elseif ($scope === 'ship') {
    // When ship scope includes UNKNOWN owner_type, avoid showing obvious base/build items
    $ands = [];
    foreach ($basePrefixes as $i => $p) { $k=":nbp$i"; $ands[]="resource_id NOT LIKE $k"; $bind[$k]=$p.'%'; }
    if ($ands) $ridExclude = " AND ".implode(' AND ', $ands);
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

  json_out(['ok'=>true, 'rows'=>$rows]);
} catch (Throwable $e) {
  error_log("[api/inventory.php] ".$e->getMessage());
  json_out(['ok'=>false,'error'=>'Internal error'], 500);
}
