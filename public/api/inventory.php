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

try {
    $pdo = db();

    // Inputs
    $scope   = strtoupper((string) param('scope', 'ALL'));   // e.g., CHARACTER/SUIT/ALL
    $limit   = max(1, min(1000, (int) param('limit', 100)));
    $offset  = max(0, (int) param('offset', 0));
    $useRecent = (strtolower((string) param('sort', '')) === 'recent');

    // WHERE clause for scope
    $whereSql = '';
    $params = [];
    if ($scope !== 'ALL') {
        // Normalize 'CHARACTER' to 'SUIT' if your data uses SUIT as the owner_type
        $ownerScope = ($scope === 'CHARACTER') ? 'SUIT' : $scope;
        $whereSql = "WHERE owner_type = :owner_scope";
        $params[':owner_scope'] = $ownerScope;
    }

    // Base view always: v_api_inventory_rows_active (provides owner_type, inventory, resource_id, amount)
    // For 'recent' we LEFT JOIN a ledger summary for ORDER BY only.
    if ($useRecent) {
        $sql = "
            SELECT a.owner_type, a.inventory, a.resource_id, a.amount
            FROM v_api_inventory_rows_recent a
            " . ($whereSql ? preg_replace('/\bowner_type\b/', 'a.owner_type', $whereSql) : '') . "
            ORDER BY a.recent_ts DESC, a.owner_type, a.inventory, a.resource_id
            LIMIT :limit OFFSET :offset
        ";

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