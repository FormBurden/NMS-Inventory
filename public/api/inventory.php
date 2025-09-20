<?php
require_once __DIR__ . '/../../includes/bootstrap.php';
header('Content-Type: application/json; charset=utf-8');

$includeTech = isset($_GET['include_tech']) && ($_GET['include_tech'] === '1' || strcasecmp($_GET['include_tech'],'true')===0);
$totals = current_totals($includeTech);

// shape rows for UI (id, amount, icon)
$out = [];
$pdo = db();
// Try to infer type from latest snapshot row (so icons can guess Product/Substance)
if (!empty($totals)) {
  $init = env('INITIAL_TABLE','nms_initial_items');
  $baselineTs = $pdo->query("SELECT MAX(snapshot_ts) FROM `$init`")->fetchColumn();
  $q = $pdo->prepare("SELECT resource_id, resource_type
                      FROM `$init` WHERE snapshot_ts = :ts GROUP BY resource_id, resource_type");
  $q->execute([':ts'=>$baselineTs]);
  $rtype = [];
  foreach ($q as $r) $rtype[strtoupper($r['resource_id'])] = $r['resource_type'];
  foreach ($totals as $rid => $amt) {
    $rt = $rtype[$rid] ?? '';
    $out[] = [
      'resource_id' => $rid,
      'display_id'  => ltrim($rid, '^'),
      'amount' => (int)$amt,
      'icon_url' => nms_icon_url($rid, $rt),
      'type' => $rt
    ];
  }
}

echo json_encode(['ok'=>true,'rows'=>$out], JSON_UNESCAPED_SLASHES);
