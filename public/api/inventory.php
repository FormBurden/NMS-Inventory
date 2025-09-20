<?php
declare(strict_types=1);

/**
 * public/api/inventory.php
 *
 * Returns inventory rows aggregated either:
 *   - for a specific save root:  GET /api/inventory.php?root=st_123...
 *   - or combined across all "active" roots (default): no ?root param
 *
 * Depends on DB views/tables created in:
 *   - v_api_inventory_rows_by_root
 *   - v_api_inventory_rows_active_combined
 *   - nms_save_roots (to mark roots active/inactive)
 *
 * This version uses mysqli. If you prefer PDO, say the word and I’ll drop a PDO variant.
 */

error_reporting(E_ALL);
ini_set('display_errors', '0');

header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');

// --- tiny .env loader (project root assumed two dirs above: public/api/ -> repo root)
$repoRoot = dirname(__DIR__, 2);
$dotenv = $repoRoot . DIRECTORY_SEPARATOR . '.env';
$env = [];
if (is_file($dotenv)) {
    foreach (file($dotenv, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        $line = trim($line);
        if ($line === '' || $line[0] === '#') continue;
        $eq = strpos($line, '=');
        if ($eq === false) continue;
        $k = trim(substr($line, 0, $eq));
        $v = trim(substr($line, $eq + 1));
        $v = trim($v, "\"'");
        $env[$k] = $v;
    }
}

$dbHost = $env['DB_HOST'] ?? 'localhost';
$dbUser = $env['DB_USER'] ?? 'nms_user';
$dbPass = $env['DB_PASS'] ?? '';
$dbName = $env['DB_NAME'] ?? 'nms_database';

// --- connect
$mysqli = @new mysqli($dbHost, $dbUser, $dbPass, $dbName);
if ($mysqli->connect_errno) {
    http_response_code(500);
    echo json_encode(['ok' => false, 'error' => 'DB connection failed: ' . $mysqli->connect_error], JSON_UNESCAPED_SLASHES);
    exit;
}
$mysqli->set_charset('utf8mb4');

// --- param
$root = isset($_GET['root']) ? trim((string)$_GET['root']) : '';
$rows = [];

try {
    if ($root !== '') {
        $sql = "SELECT resource_id, amount, item_type
                FROM v_api_inventory_rows_by_root
                WHERE save_root = ?";
        $stmt = $mysqli->prepare($sql);
        if (!$stmt) {
            throw new RuntimeException('prepare failed: ' . $mysqli->error);
        }
        $stmt->bind_param('s', $root);
        if (!$stmt->execute()) {
            throw new RuntimeException('execute failed: ' . $stmt->error);
        }
        $res = $stmt->get_result();
    } else {
        $sql = "SELECT resource_id, amount, item_type
                FROM v_api_inventory_rows_active_combined";
        $res = $mysqli->query($sql);
        if (!$res) {
            throw new RuntimeException('query failed: ' . $mysqli->error);
        }
    }

    while ($r = $res->fetch_assoc()) {
        $rid = $r['resource_id'];
        $rows[] = [
            'resource_id' => $rid,
            'amount'      => (int)$r['amount'],
            // Keep your icon scheme exactly as before:
            'icon_url'    => "https://nomanssky.fandom.com/wiki/Special:FilePath/PRODUCT.$rid.png",
            'type'        => $r['item_type'],
        ];
    }

    echo json_encode(['ok' => true, 'rows' => $rows], JSON_UNESCAPED_SLASHES);
} catch (Throwable $e) {
    http_response_code(500);
    echo json_encode(['ok' => false, 'error' => $e->getMessage()], JSON_UNESCAPED_SLASHES);
} finally {
    if (isset($res) && $res instanceof mysqli_result) $res->free();
    if (isset($stmt) && $stmt instanceof mysqli_stmt) $stmt->close();
    $mysqli->close();
}
