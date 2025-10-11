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
