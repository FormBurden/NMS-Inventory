<?php
declare(strict_types=1);

/**
 * Inventory API
 * - Preserves existing response shape { ok, rows: [{ owner_type, inventory, resource_id, amount }] }
 * - Adds snapshot_ts derived from storage/decoded/_manifest_recent.json (top-level and per-row)
 * - Keeps 'sort=recent' behavior by joining ledger deltas for ordering only
 *
 * Requirements:
 *   - includes/db.php must provide $pdo (PDO) or get_db() returning PDO
 */

require_once __DIR__ . '/../../includes/db.php';

header('Content-Type: application/json; charset=utf-8');

function db(): PDO {
    if (function_exists('get_db')) {
        return get_db();
    }
    global $pdo;
    if ($pdo instanceof PDO) return $pdo;
    http_response_code(500);
    echo json_encode(['ok' => false, 'error' => 'DB not initialized']);
    exit;
}

/**
 * Read snapshot_ts from manifest written by the pipeline:
 *   storage/decoded/_manifest_recent.json
 * The manifest is atomically written as .tmp then moved into place by the pipeline.
 */
function read_manifest_snapshot_ts(): ?string {
    $root = realpath(__DIR__ . '/../../');
    if ($root === false) return null;
    $path = $root . '/storage/decoded/_manifest_recent.json';
    if (!is_file($path)) return null;
    $json = @file_get_contents($path);
    if ($json === false) return null;
    $obj = json_decode($json, true);
    if (!is_array($obj)) return null;

    // Prefer explicit 'snapshot_ts' if present; otherwise fall back to first item mtime
    if (!empty($obj['snapshot_ts']) && is_string($obj['snapshot_ts'])) {
        return $obj['snapshot_ts'];
    }
    if (!empty($obj['items']) && is_array($obj['items'])) {
        $it = $obj['items'][0] ?? null;
        if (is_array($it) && !empty($it['source_mtime']) && is_string($it['source_mtime'])) {
            return $it['source_mtime'];
        }
    }
    return null;
}

function param(string $key, $default = null) {
    return $_GET[$key] ?? $default;
}

function view_exists(PDO $pdo, string $name): bool {
    $sql = "SELECT 1
              FROM information_schema.VIEWS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :name
             LIMIT 1";
    $st = $pdo->prepare($sql);
    $st->execute([':name' => $name]);
    return (bool) $st->fetchColumn();
}

try {

    $pdo = db();

    // Inputs
    $scope       = strtoupper((string) param('scope', 'ALL'));   // e.g., CHARACTER/SUIT/ALL
    $limit       = max(1, min(1000, (int) param('limit', 100)));
    $offset      = max(0, (int) param('offset', 0));
    $useRecent   = (strtolower((string) param('sort', '')) === 'recent');
    $includeTech = ((string) param('include_tech', '0') === '1');

    $whereSql = '';
    $params = [];

    if ($scope !== 'ALL') {
        // Support comma-separated scopes (e.g., "frigate,corvette") and normalize common plural -> singular
        $scopes = array_values(array_filter(array_map('strtolower', array_map('trim', explode(',', (string)$scope)))));
        $norm = static function(string $s): string {
            return $s === 'vehicles' ? 'vehicle' : $s;
        };
        $scopes = array_map($norm, $scopes);

        if (count($scopes) === 1) {
            $whereSql = "WHERE LOWER(owner_type) = :owner_scope";
            $params[':owner_scope'] = $scopes[0];
        } else {
            $in = [];
            foreach ($scopes as $i => $s) {
                $ph = ":s{$i}";
                $in[] = $ph;
                $params[$ph] = $s;
            }
            if ($in) {
                $whereSql = "WHERE LOWER(owner_type) IN (" . implode(',', $in) . ")";
            }
        }
    }


    // Build SQL with view detection + base-table fallback so Include Tech works even if views are missing.
    $haveActive = view_exists($pdo, 'v_api_inventory_rows_active');
    $haveRecent = view_exists($pdo, 'v_api_inventory_rows_recent');

    // If Include Tech is OFF we need item_type filtering, which the views may not expose.
    // In that case prefer a base-table query against the newest snapshot.
    $useBaseForTechFilter = ($includeTech === false);

    // Owner filter exists as a WHERE ... clause built above; convert to "AND (...)" for base-table WHERE
    $ownerFilter = '';
    if ($whereSql) {
        $ownerFilter = ' AND ' . preg_replace('/^\s*WHERE\s*/i', '', $whereSql);
    }

    if ($useBaseForTechFilter || (!$haveActive && !$haveRecent)) {
        // Base-table fallback, honors Include Tech and Scope.
        // Newest snapshot only; amounts are aggregated per owner/inventory/resource.
        $sql = "
            SELECT owner_type, inventory, resource_id, SUM(amount) AS amount
              FROM nms_items
             WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM nms_snapshots)
               " . ($includeTech ? "" : " AND item_type <> 'Technology' ") . "
               $ownerFilter
          GROUP BY owner_type, inventory, resource_id
          ORDER BY owner_type, inventory, resource_id
             LIMIT :limit OFFSET :offset
        ";
    } else {
        // View path: keep your existing sort behaviors if views are present.
        if ($useRecent && $haveRecent) {
            $sql = "
                SELECT owner_type, inventory, resource_id, amount
                FROM v_api_inventory_rows_recent
                " . ($whereSql ?: "") . "
                ORDER BY recent_ts DESC, owner_type, inventory, resource_id
                LIMIT :limit OFFSET :offset
            ";
        } else {
            $sql = "
                SELECT owner_type, inventory, resource_id, amount
                FROM v_api_inventory_rows_active
                " . ($whereSql ?: "") . "
                ORDER BY owner_type, inventory, resource_id
                LIMIT :limit OFFSET :offset
            ";
        }
    }


    $stmt = $pdo->prepare($sql);
    foreach ($params as $k => $v) {
        $stmt->bindValue($k, $v, PDO::PARAM_STR);
    }
    $stmt->bindValue(':limit',  $limit,  PDO::PARAM_INT);
    $stmt->bindValue(':offset', $offset, PDO::PARAM_INT);
    $stmt->execute();

    $rows = $stmt->fetchAll(PDO::FETCH_ASSOC) ?: [];

    // Attach snapshot_ts from manifest (top-level + per-row for UI convenience)
    $snapshotTs = read_manifest_snapshot_ts();
    if ($snapshotTs) {
        foreach ($rows as &$r) {
            $r['snapshot_ts'] = $snapshotTs;
        }
        unset($r);
    }

    echo json_encode([
        'ok' => true,
        'snapshot_ts' => $snapshotTs,  // top-level hint (non-breaking)
        'rows' => $rows,
    ], JSON_UNESCAPED_SLASHES);
} catch (Throwable $e) {
    http_response_code(500);
    echo json_encode([
        'ok' => false,
        'error' => 'Query failed',
        'detail' => $e->getMessage(),
    ], JSON_UNESCAPED_SLASHES);
}