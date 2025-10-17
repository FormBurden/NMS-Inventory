<?php
// public/api/inventory.php
// Returns inventory rows with optional "Recent first" ordering.
//
// Query params:
//   scope=<owner scope>                (e.g., character, ship, freighter, storage, vehicle, all)
//   include_tech=1                     (include tech items; default excludes tech)
//   limit=<N>                          (default 100)
//   sort=recent                        (enable recency ordering & 'changed_at' in payload)

declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');

$ROOT = dirname(__DIR__, 2);

// --- DB bootstrap ------------------------------------------------------------
require_once $ROOT . '/includes/db.php'; // should expose $pdo (PDO). If your include uses $db, we alias below.
if (!isset($pdo) && isset($db) && $db instanceof PDO) {
    $pdo = $db;
}
if (!isset($pdo) || !($pdo instanceof PDO)) {
    http_response_code(500);
    echo json_encode(['error' => 'Database handle ($pdo) not available']);
    exit;
}

// --- Inputs ------------------------------------------------------------------
$limit = isset($_GET['limit']) ? max(1, (int)$_GET['limit']) : 100;
$limit = min($limit, 500); // cap

$scope        = isset($_GET['scope']) ? trim((string)$_GET['scope']) : 'all';
$includeTech  = isset($_GET['include_tech']) && (string)$_GET['include_tech'] === '1';
$wantRecent   = isset($_GET['sort']) && strtolower((string)$_GET['sort']) === 'recent';

// Map friendly scope to one or more owner_type values actually stored in DB.
// Adjust these to match your schema if needed.
$SCOPE_MAP = [
    'character' => ['CHARACTER', 'EXOSUIT', 'SUIT'],
    'ship'      => ['SHIP'],
    'freighter' => ['FREIGHTER'],
    'storage'   => ['STORAGE', 'CONTAINER', 'STORAGE_CONTAINER'],
    'vehicle'   => ['VEHICLE', 'EXOCRAFT'],
    'all'       => [], // no filter
];

// Build owner_type filter list (distinct values allowed).
$ownerTypes = [];
if (isset($SCOPE_MAP[$scope])) {
    $ownerTypes = $SCOPE_MAP[$scope];
} elseif ($scope !== 'all' && $scope !== '') {
    // Accept raw owner_type value passthrough if caller already knows exact key.
    $ownerTypes = [$scope];
}

// --- SQL Fragments -----------------------------------------------------------
// NOTE: We source current quantities from v_api_inventory_rows_active (your existing view).
// We join resources for names and compute recency via two pre-aggregated subqueries:
//   L: last ledger delta per (resource_id, owner_type)
//   S: last snapshot imported_at where the item appears (via nms_items -> nms_snapshots)

$techFilterSql = $includeTech ? '' : "AND a.item_type <> 'TECH'";

$whereOwnerSql = '';
$params = [];
if (!empty($ownerTypes)) {
    $placeholders = implode(',', array_fill(0, count($ownerTypes), '?'));
    $whereOwnerSql = "AND a.owner_type IN ($placeholders)";
    foreach ($ownerTypes as $ot) {
        $params[] = $ot;
    }
}

$selectCommon = "
    a.resource_id,
    a.owner_type,
    COALESCE(res.display_name, res.name, res.code) AS name,
    SUM(a.amount) AS amount,
    MIN(a.item_type) AS item_type
";

$joinCommon = "
    LEFT JOIN nms_resources AS res
      ON res.resource_id = a.resource_id
";

$groupCommon = "GROUP BY a.resource_id, a.owner_type, COALESCE(res.display_name, res.name, res.code)";

// Pre-aggregations for recency
$joinRecent = "
    LEFT JOIN (
        SELECT resource_id, owner_type, MAX(applied_at) AS max_applied_at
        FROM nms_ledger_deltas
        GROUP BY resource_id, owner_type
    ) AS L
      ON L.resource_id = a.resource_id
     AND L.owner_type  = a.owner_type
    LEFT JOIN (
        SELECT i.resource_id, i.owner_type, MAX(s.imported_at) AS max_imported_at
        FROM nms_items i
        JOIN nms_snapshots s ON s.snapshot_id = i.snapshot_id
        GROUP BY i.resource_id, i.owner_type
    ) AS S
      ON S.resource_id = a.resource_id
     AND S.owner_type  = a.owner_type
";

try {
    if ($wantRecent) {
        // Recent-first path: compute changed_at with ledger primary, snapshot fallback.
        $sql = "
            SELECT
                $selectCommon,
                COALESCE(L.max_applied_at, S.max_imported_at) AS changed_at
            FROM v_api_inventory_rows_active AS a
            $joinCommon
            $joinRecent
            WHERE 1=1
              $whereOwnerSql
              $techFilterSql
            $groupCommon
            ORDER BY
              (COALESCE(L.max_applied_at, S.max_imported_at) IS NULL) ASC,
              COALESCE(L.max_applied_at, S.max_imported_at) DESC,
              SUM(a.amount) DESC
            LIMIT $limit
        ";
    } else {
        // Default path: amount-desc; include name for UI consistency.
        $sql = "
            SELECT
                $selectCommon
            FROM v_api_inventory_rows_active AS a
            $joinCommon
            WHERE 1=1
              $whereOwnerSql
              $techFilterSql
            $groupCommon
            ORDER BY SUM(a.amount) DESC
            LIMIT $limit
        ";
    }

    $stmt = $pdo->prepare($sql);
    $stmt->execute($params);
    $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);
    // Fallback: if scoped query returned zero rows, include UNKNOWN owner_type and retry.
    // This helps when importer produced owner_type=UNKNOWN (e.g., obfuscated JSON paths).
    if (empty($rows) && !empty($ownerTypes) && !in_array('UNKNOWN', $ownerTypes, true)) {
        $ownerTypes2 = array_values(array_unique(array_merge($ownerTypes, ['UNKNOWN'])));
    
        // Rebuild WHERE + params
        $placeholders2 = implode(',', array_fill(0, count($ownerTypes2), '?'));
        $whereOwnerSql2 = "AND a.owner_type IN ($placeholders2)";
        $params2 = $ownerTypes2;
    
        // Rebuild SQL and retry with the augmented owner set
        if ($wantRecent) {
        $sql2 = "
            SELECT
            $selectCommon,
            COALESCE(L.max_applied_at, S.max_imported_at) AS changed_at
            FROM v_api_inventory_rows_active AS a
            $joinCommon
            $joinRecent
            WHERE 1=1
            $whereOwnerSql2
            $techFilterSql
            $groupCommon
            ORDER BY
            (COALESCE(L.max_applied_at, S.max_imported_at) IS NULL) ASC,
            COALESCE(L.max_applied_at, S.max_imported_at) DESC,
            SUM(a.amount) DESC
            LIMIT $limit
        ";
        } else {
        $sql2 = "
            SELECT
            $selectCommon
            FROM v_api_inventory_rows_active AS a
            $joinCommon
            WHERE 1=1
            $whereOwnerSql2
            $techFilterSql
            $groupCommon
            ORDER BY SUM(a.amount) DESC
            LIMIT $limit
        ";
        }
    
        $stmt = $pdo->prepare($sql2);
        $stmt->execute($params2);
        $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);
    
        // Reflect the augmented owner_types in the response meta
        $ownerTypes = $ownerTypes2;
    }
    

    // Shape the response
    $payload = [
        'ok'   => true,
        'rows' => $rows,
        'meta' => [
            'scope'        => $scope,
            'owner_types'  => $ownerTypes,
            'include_tech' => $includeTech,
            'limit'        => $limit,
            'sort'         => $wantRecent ? 'recent' : 'amount_desc',
        ],
    ];

    echo json_encode($payload);
} catch (Throwable $e) {
    http_response_code(500);
    echo json_encode([
        'ok'    => false,
        'error' => 'Query failed',
        'detail'=> $e->getMessage(),
    ]);
}
