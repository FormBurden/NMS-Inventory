<?php
declare(strict_types=1);

require_once __DIR__ . '/../../includes/db.php';
require_once __DIR__ . '/../../includes/icon_map.php';

header('Content-Type: application/json');

try {
    $includeTech = isset($_GET['include_tech']) && $_GET['include_tech'] !== '0';
    $totals = current_totals($includeTech);

    $rows = [];
    if (!empty($totals)) {
        $rtype = baseline_resource_types(); // id (UPPER) => type
        foreach ($totals as $rid => $amt) {
            $type = $rtype[$rid] ?? '';
            $rows[] = [
                'resource_id' => $rid,
                'display_id'  => ltrim($rid, '^'),
                'amount'      => (int)$amt,
                'icon_url'    => nms_icon_url($rid, (string)$type),
                'type'        => $type,
            ];
        }
    }

    echo json_encode(['ok' => true, 'rows' => $rows], JSON_UNESCAPED_SLASHES);
} catch (Throwable $e) {
    http_response_code(500);
    echo json_encode(['ok' => false, 'error' => $e->getMessage()]);
}
