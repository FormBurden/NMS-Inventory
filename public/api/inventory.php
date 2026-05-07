<?php
declare(strict_types=1);

require_once __DIR__ . '/../../includes/db.php';
if (is_file(__DIR__ . '/../../includes/bootstrap.php')) require_once __DIR__ . '/../../includes/bootstrap.php';
header('Content-Type: application/json; charset=utf-8');

function db(): PDO {
    if (function_exists('get_db')) return get_db();
    global $pdo; if ($pdo instanceof PDO) return $pdo;
    http_response_code(500);
    echo json_encode(['ok'=>false,'error'=>'DB not initialized'], JSON_UNESCAPED_SLASHES);
    exit;
}
function jexit($d,int $c=200){ http_response_code($c); echo json_encode($d, JSON_UNESCAPED_SLASHES); exit; }

function read_snapshot_ts(): ?string {
    $p = realpath(__DIR__ . '/../../storage/decoded/_manifest_recent.json');
    if (!$p || !is_file($p)) return null;
    $s = @file_get_contents($p); if ($s===false) return null;
    $o = json_decode($s, true);
    if (!is_array($o)) return null;
    if (!empty($o['snapshot_ts']) && is_string($o['snapshot_ts'])) return $o['snapshot_ts'];
    $it = $o['items'][0] ?? null;
    return (is_array($it) && !empty($it['source_mtime'])) ? (string)$it['source_mtime'] : null;
}

function view_exists(PDO $pdo, string $name): bool {
    $q = "SELECT 1 FROM information_schema.VIEWS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :n LIMIT 1";
    $st = $pdo->prepare($q); if(!$st) return false;
    return $st->execute([':n'=>$name]) && (bool)$st->fetchColumn();
}

try {
    $pdo = db();
    $limit = max(1, min(1000, (int)($_GET['limit'] ?? 500)));
    $offset = max(0, (int)($_GET['offset'] ?? 0));
    $includeTech = (($_GET['includeTech'] ?? '0') === '1');
    $sort = strtolower((string)($_GET['sort'] ?? ''));
    $scope = (string)($_GET['scope'] ?? 'ALL');
    $snapshotTs = read_snapshot_ts();

    $where = ''; $params = [];
    if (strtoupper($scope) !== 'ALL') {
        $scopes = array_values(array_filter(array_map('trim', explode(',', strtolower($scope)))));
        $scopes = array_map(static fn($s)=>$s==='vehicles'?'vehicle':$s, $scopes);
        if ($scopes) {
            $ph=[]; foreach($scopes as $i=>$s){ $k=":s{$i}"; $ph[]=$k; $params[$k]=$s; }
            $where = "WHERE LOWER(owner_type) IN (".implode(',', $ph).")";
        }
    }

    $haveActive = view_exists($pdo,'v_api_inventory_rows_active');
    $haveRecent = view_exists($pdo,'v_api_inventory_rows_recent');
    $useRecent  = ($sort === 'recent') && $haveRecent;

    if (!$includeTech) {
        $ownerFilter = $where ? preg_replace('/^WHERE\s+/i','AND ',$where) : '';
        $sql = "
          SELECT owner_type, inventory, resource_id, SUM(amount) AS amount
            FROM nms_items
           WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM nms_snapshots)
             AND UPPER(inventory) <> 'TECHNOLOGY' AND UPPER(item_type) <> 'TECHNOLOGY'
             $ownerFilter
        GROUP BY owner_type, inventory, resource_id
        ORDER BY ".($useRecent?'resource_id':'owner_type, inventory, resource_id')."
           LIMIT :limit OFFSET :offset";
    } elseif ($useRecent) {
        $sql = "
          SELECT owner_type, inventory, resource_id, amount
            FROM v_api_inventory_rows_recent
            ".($where?:'')."
        ORDER BY recent_ts DESC, owner_type, inventory, resource_id
           LIMIT :limit OFFSET :offset";
    } elseif ($haveActive) {
        $sql = "
          SELECT owner_type, inventory, resource_id, amount
            FROM v_api_inventory_rows_active
            ".($where?:'')."
        ORDER BY owner_type, inventory, resource_id
           LIMIT :limit OFFSET :offset";
    } else {
        $ownerFilter = $where ? preg_replace('/^WHERE\s+/i','AND ',$where) : '';
        $sql = "
          SELECT owner_type, inventory, resource_id, SUM(amount) AS amount
            FROM nms_items
           WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM nms_snapshots)
             $ownerFilter
        GROUP BY owner_type, inventory, resource_id
        ORDER BY owner_type, inventory, resource_id
           LIMIT :limit OFFSET :offset";
    }

    $st = $pdo->prepare($sql); if(!$st) throw new RuntimeException('Prepare failed');
    foreach($params as $k=>$v){ $st->bindValue($k,$v,PDO::PARAM_STR); }
    $st->bindValue(':limit',$limit,PDO::PARAM_INT);
    $st->bindValue(':offset',$offset,PDO::PARAM_INT);
    if(!$st->execute()) throw new RuntimeException('Execute failed');
    $rows = $st->fetchAll(PDO::FETCH_ASSOC) ?: [];

    jexit(['ok'=>true,'snapshot_ts'=>$snapshotTs,'rows'=>$rows]);
} catch (Throwable $e) {
    jexit(['ok'=>false,'error'=>'Query failed','detail'=>$e->getMessage()], 500);
}
