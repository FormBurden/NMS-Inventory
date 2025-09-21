<?php
declare(strict_types=1);

/**
 * Central DB connection for NMS-Inventory.
 * Reads NMS_DB_* env vars with safe fallbacks and keeps backward-compat with legacy DB_* names.
 */

if (!function_exists('nms_env_multi')) {
    /**
     * Return the first non-empty environment value from a list of names.
     * @param string[] $names
     * @param ?string $default
     */
    function nms_env_multi(array $names, ?string $default = null): ?string {
        foreach ($names as $n) {
            $v = getenv($n);
            if ($v !== false && $v !== '') {
                return $v;
            }
        }
        return $default;
    }
}

/* Optional: lightweight .env loader (only sets vars not already in process env) */
$envPath = dirname(__DIR__) . '/.env';
if (is_file($envPath)) {
    $lines = @file($envPath, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    if ($lines !== false) {
        foreach ($lines as $line) {
            $line = trim($line);
            if ($line === '' || $line[0] === '#') continue;
            if (strpos($line, '=') === false) continue;
            [$k, $v] = explode('=', $line, 2);
            $k = trim($k);
            $v = trim($v);
            $v = trim($v, "'\"");
            if (getenv($k) === false) {
                putenv($k . '=' . $v);
            }
        }
    }
}

/* Back-compat shim: if legacy DB_* names are unset, mirror NMS_DB_* into them */
foreach (['HOST','PORT','USER','PASS','NAME'] as $sfx) {
    $legacy = 'DB_' . $sfx;
    $modern = 'NMS_DB_' . $sfx;
    if ((getenv($legacy) === false || getenv($legacy) === '') && (getenv($modern) !== false && getenv($modern) !== '')) {
        putenv($legacy . '=' . getenv($modern));
    }
}

/* Resolve connection parameters (NMS_DB_* first, then legacy aliases, then sensible defaults) */
$host = nms_env_multi(['NMS_DB_HOST','DB_HOST','MYSQL_HOST'], '127.0.0.1');
$port = nms_env_multi(['NMS_DB_PORT','DB_PORT','MYSQL_PORT'], '3306');
$user = nms_env_multi(['NMS_DB_USER','DB_USER','MYSQL_USER'], 'nms_user');
$pass = nms_env_multi(['NMS_DB_PASS','DB_PASS','MYSQL_PASSWORD','MYSQL_PASS','MYSQL_PWD'], '');
$name = nms_env_multi(['NMS_DB_NAME','DB_NAME','MYSQL_DATABASE'], 'nms_database');

/* Build DSN and connect */
$dsn = "mysql:host={$host};port={$port};dbname={$name};charset=utf8mb4";

$options = [
    PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
    PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    PDO::ATTR_EMULATE_PREPARES   => false,
];

/**
 * Get a singleton PDO.
 * @return PDO
 */
function nms_db(): PDO {
    static $pdo = null;
    if ($pdo instanceof PDO) return $pdo;

    global $dsn, $user, $pass, $options;
    $pdo = new PDO($dsn, $user, $pass, $options);
    return $pdo;
}

/* Legacy alias expected by existing code (e.g., inventory.php, settings.php) */
if (!function_exists('db')) {
    /**
     * @return PDO
     */
    function db(): PDO {
        return nms_db();
    }
}

/* Also expose $pdo for existing includes that expect it */
$pdo = nms_db();

return $pdo;
