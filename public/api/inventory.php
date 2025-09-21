<?php
declare(strict_types=1);

/**
 * public/api/inventory.php
 *
 * GET /api/inventory.php
 * GET /api/inventory.php?root=st_7656...
 *
 * Requires DB objects:
 *   - v_api_inventory_rows_by_root (resource_id, amount, item_type, save_root)
 *   - v_api_inventory_rows_active_combined (resource_id, amount, item_type)
 *   - nms_save_roots (used by the combined view to determine "active")
 */

error_reporting(E_ALL);
ini_set('display_errors', '0');

header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');

/** Load .env from repo root (two dirs up from public/api/) */
$REPO_ROOT = dirname(__DIR__, 2);
$DOTENV = $REPO_ROOT . DIRECTORY_SEPARATOR . '.env';

/** Very small .env parser (KEY=VALUE, ignores # comments) */
function load_env_file(string $path): array {
    $out = [];
    if (!is_file($path)) return $out;
    foreach (file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        $line = trim($line);
        if ($line === '' || $line[0] === '#') continue;
        $eq = strpos($line, '=');
        if ($eq === false) continue;
        $k = rtrim(substr($line, 0, $eq));
        $v = ltrim(substr($line, $eq + 1));
        // strip optional quotes
        if (($v[0] ?? '') === '"' && substr($v, -1) === '"') $v = substr($v, 1, -1);
        if (($v[0] ?? '') === "'" && substr($v, -1) === "'") $v = substr($v, 1, -1);
        $out[$k] = $v;
        // also expose to getenv()
        if (!getenv($k)) putenv("$k=$v");
        $_ENV[$k] = $v;
        $_SERVER[$k] = $v;
    }
    return $out;
}
load_env_file($DOTENV);

/** Helper to read env with multiple possible names + default */
function env(array $names, $default = null) {
    foreach ($names as $n) {
        $v = getenv($n);
        if ($v !== false && $v !== null && $v !== '') return $v;
    }
    return $default;
}

/** DB config (supports both NMS_DB_* and DB_* names) */
$DB_HOST   = env(['NMS_DB_HOST','DB_HOST'], 'localhost');
$DB_PORT   = (int) env(['NMS_DB_PORT','DB_PORT'], '3306');
$DB_NAME   = env(['NMS_DB_NAME','DB_NAME'], 'nms_database');
$DB_USER   = env(['NMS_DB_USER','DB_USER'], 'nms_user');
$DB_PASS   = (string) (env(['NMS_DB_PASS','DB_PASS'], '') ?? ''); // ensure string, not null
$DB_SOCKET = env(['NMS_DB_SOCKET','DB_SOCKET'], null);            // e.g. /run/mysqld/mysqld.sock

/** Fail fast if password is still missing (prevents "using password: NO") */
if ($DB_PASS === '') {
    http_response_code(500);
    echo json_encode([
        'ok' => false,
        'error' => 'Database password is empty. Set NMS_DB_PASS (or DB_PASS) in .env at repo root.'
    ], JSON_UNESCAPED_SLASHES);
    exit;
}

$mysqli = mysqli_init();
$mysqli->options(MYSQLI_OPT_INT_AND_FLOAT_NATIVE, 1);

// Connect via socket if provided, otherwise host/port.
$connected = $DB_SOCKET
    ? @$mysqli->real_connect($DB_HOST, $DB_USER, $DB_PASS, $DB_NAME, null, $DB_SOCKET)
    : @$mysqli->real_connect($DB_HOST, $DB_USER, $DB_PASS, $DB_NAME, $DB_PORT);

if (!$connected) {
    http_response_code(500);
    echo json_encode([
        'ok' => false,
        'error' => 'DB connection failed: ' . mysqli_connect_error()
    ], JSON_UNESCAPED_SLASHES);
    exit;
}

try {
    // Inputs
    $root        = isset($_GET['root']) ? trim((string)$_GET['root']) : '';
    $scope       = isset($_GET['scope']) ? strtolower(trim((string)$_GET['scope'])) : '';
    $includeTech = isset($_GET['include_tech']) && $_GET['include_tech'] === '1';
    $rows = [];


    if ($root !== '') {
        // simple guard; allow alnum + underscore
        if (!preg_match('/^[A-Za-z0-9_.-]+$/', $root)) {
            throw new RuntimeException('Invalid root format.');
        }
        $sql = "SELECT resource_id, amount, item_type
                FROM v_api_inventory_rows_by_root
                WHERE save_root = ?";
        $stmt = $mysqli->prepare($sql);
        if (!$stmt) throw new RuntimeException('prepare failed: ' . $mysqli->error);
        $stmt->bind_param('s', $root);
        if (!$stmt->execute()) throw new RuntimeException('execute failed: ' . $stmt->error);
        $res = $stmt->get_result();
    } elseif ($scope !== '') {
        // map ui scope -> owner_type prefixes (case-insensitive)
        $scopeOwners = [
            'character' => ['CHAR','CHARACTER','EXOSUIT','SUIT'],
            'base'      => ['BASE'],
            'storage'   => ['STORAGE','CONTAINER'],
            'frigate'   => ['FRIGATE'],
            'corvette'  => ['FREIGHTER','CORVETTE','CAPITAL','CAPSHIP'],
            'ship'      => ['SHIP','STARSHIP'],
            'vehicles'  => ['VEHICLE','EXOCRAFT','EXO_CRAFT','VEHICLES'],
        ];
        $owners = $scopeOwners[$scope] ?? [];
        if (!$owners) {
            throw new RuntimeException('Unsupported scope.');
        }

        // latest active snapshot
        $rs = $mysqli->query("SELECT snapshot_id FROM nms_snapshots ORDER BY imported_at DESC LIMIT 1");
        if (!$rs) throw new RuntimeException('query failed: ' . $mysqli->error);
        $snap = $rs->fetch_assoc();
        if (!$snap) throw new RuntimeException('No snapshots found.');
        $snapshotId = (int) $snap['snapshot_id'];
        $rs->free();

        // owner_type LIKE conditions + optional TECHONLY filter
        $like  = [];
        $types = 'i';
        $bind  = [$snapshotId];
        foreach ($owners as $o) {
            $like[] = "UPPER(owner_type) LIKE ?";
            $bind[] = strtoupper($o) . '%';
            $types .= 's';
        }
        $techSql = $includeTech ? "" : " AND UPPER(inventory) <> 'TECHONLY'";

        $sql = "SELECT resource_id, SUM(amount) AS amount, MIN(item_type) AS item_type
                FROM nms_items
                WHERE snapshot_id = ?{$techSql}
                  AND (" . implode(' OR ', $like) . ")
                GROUP BY resource_id";
        $stmt = $mysqli->prepare($sql);
        if (!$stmt) throw new RuntimeException('prepare failed: ' . $mysqli->error);
        $stmt->bind_param($types, ...$bind);
        if (!$stmt->execute()) throw new RuntimeException('execute failed: ' . $stmt->error);
        $res = $stmt->get_result();
    } else {
        $sql = "SELECT resource_id, amount, item_type
                FROM v_api_inventory_rows_active_combined";
        $res = $mysqli->query($sql);
        if (!$res) throw new RuntimeException('query failed: ' . $mysqli->error);
    }



    while ($r = $res->fetch_assoc()) {
        $rid = $r['resource_id'];
        $rows[] = [
            'resource_id' => $rid,
            'amount'      => (int) $r['amount'],
            // Keep your previous icon URL scheme:
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
    if ($mysqli instanceof mysqli) $mysqli->close();
}
