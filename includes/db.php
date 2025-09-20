<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';

/**
 * Shared PDO.
 */
function db(): PDO {
    static $pdo = null;
    if ($pdo instanceof PDO) return $pdo;

    $host = env('DB_HOST', '127.0.0.1');
    $port = (string)env('DB_PORT', '3306');
    $name = env('DB_NAME', 'nms_database');
    $user = env('DB_USER', '');
    $pass = env('DB_PASS', '');

    $dsn = "mysql:host={$host};port={$port};dbname={$name};charset=utf8mb4";
    $pdo = new PDO($dsn, $user, $pass, [
        PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);
    return $pdo;
}

/**
 * Current totals per resource_id.
 *
 * Strategy:
 *  - Use latest snapshot_ts from INITIAL_TABLE as baseline
 *  - Sum amounts at that baseline (optionally excluding Technology)
 *  - Add summed net from LEDGER_TABLE for sessions after that baseline
 */
function current_totals(bool $includeTech = false): array {
    $pdo  = db();
    $init = (string)env('INITIAL_TABLE', 'nms_initial_items');
    $ledg = (string)env('LEDGER_TABLE',  'nms_ledger_deltas');

    $baselineTs = $pdo->query("SELECT MAX(snapshot_ts) AS ts FROM `$init`")->fetchColumn();
    if (!$baselineTs) return [];

    $params = [':ts' => $baselineTs];
    $techFilter = $includeTech ? "" : " AND resource_type <> 'Technology' ";

    // Baseline snapshot totals
    $sqlBase = "SELECT UPPER(resource_id) AS resource_id, SUM(amount) AS amt
                FROM `$init`
                WHERE snapshot_ts = :ts $techFilter
                GROUP BY UPPER(resource_id)";
    $base = $pdo->prepare($sqlBase);
    $base->execute($params);

    $totals = [];
    foreach ($base as $r) {
        $totals[$r['resource_id']] = (int)$r['amt'];
    }

    // Ledger net since baseline
    if ($pdo->query("SHOW TABLES LIKE ".$pdo->quote($ledg))->rowCount() > 0) {
        $sqlLed = "SELECT UPPER(resource_id) AS resource_id, SUM(net) AS net
                   FROM `$ledg`
                   WHERE session_end >= :ts
                   GROUP BY UPPER(resource_id)";
        $led = $pdo->prepare($sqlLed);
        $led->execute($params);
        foreach ($led as $r) {
            $k = $r['resource_id'];
            $totals[$k] = ($totals[$k] ?? 0) + (int)$r['net'];
        }
    }

    return $totals;
}

/**
 * Resource types at the latest baseline (id => type).
 * Helps the API decide which icon URL heuristic to use.
 */
function baseline_resource_types(): array {
    $pdo  = db();
    $init = (string)env('INITIAL_TABLE', 'nms_initial_items');
    $ts   = $pdo->query("SELECT MAX(snapshot_ts) AS ts FROM `$init`")->fetchColumn();
    if (!$ts) return [];
    $q = $pdo->prepare(
        "SELECT UPPER(resource_id) AS resource_id, MIN(resource_type) AS resource_type
         FROM `$init` WHERE snapshot_ts = :ts
         GROUP BY UPPER(resource_id)"
    );
    $q->execute([':ts' => $ts]);

    $out = [];
    foreach ($q as $r) $out[$r['resource_id']] = $r['resource_type'];
    return $out;
}
