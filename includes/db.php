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

  $ts = $pdo->query("SELECT MAX(snapshot_ts) AS ts FROM `$init`")->fetchColumn();
  if (!$ts) return [];

  $techFilter = $includeTech ? "" : " AND resource_type <> 'Technology' ";

  $sql = "SELECT UPPER(resource_id) AS resource_id, SUM(amount) AS amt
          FROM `$init`
          WHERE snapshot_ts = :ts $techFilter
          GROUP BY UPPER(resource_id)";
  $stmt = $pdo->prepare($sql);
  $stmt->execute([':ts'=>$ts]);

  $out = [];
  foreach ($stmt as $r) $out[$r['resource_id']] = (int)$r['amt'];
  return $out;
}

