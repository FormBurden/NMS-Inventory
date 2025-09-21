<?php
declare(strict_types=1);

require_once __DIR__ . '/../../includes/db.php';
header('Content-Type: application/json');

try {
    $scope = strtolower($_GET['scope'] ?? 'ship');
    $limit = max(1, min((int)($_GET['limit'] ?? 500), 2000));

    // UI scopes → canonical owner_type values in DB
    $SCOPE_TO_OWNERS = [
        'ship'      => ['SHIP'],
        'character' => ['SUIT'],
        'storage'   => ['STORAGE'],
        'frigate'   => ['FRIGATE'],
        'vehicles'  => ['VEHICLE'],

        // friendly aliases
        'freighter' => ['FRIGATE'],
        'corvette'  => ['FRIGATE'],
        'base'      => ['STORAGE'],
    ];

    // Resolve owners for this scope
    $owners = $SCOPE_TO_OWNERS[$scope] ?? ['SHIP'];
    if (!$owners) $owners = ['SHIP'];

    // Optional inventory filter (?inv=GENERAL|TECHONLY|CARGO)
    $inv = strtoupper(trim((string)($_GET['inv'] ?? '')));
    $invAllowed = ['GENERAL','TECHONLY','CARGO'];
    $invSql = '';
    $params = $owners;

    if ($inv && in_array($inv, $invAllowed, true)) {
        $invSql = ' AND inventory = ?';
        $params[] = $inv;
    }

    // Build owners placeholder list: ?, ?, ...
    $placeholders = implode(',', array_fill(0, count($owners), '?'));

    // Use the active rows view which now exposes owner_type & inventory
    $sql = "
        SELECT
            resource_id,
            SUM(amount)     AS amount,
            MIN(item_type)  AS item_type
        FROM v_api_inventory_rows_active
        WHERE owner_type IN ($placeholders)
        $invSql
        GROUP BY resource_id
        ORDER BY amount DESC
        LIMIT $limit
    ";

    $stmt = db()->prepare($sql);
    $stmt->execute($params);
    $rows = $stmt->fetchAll();

    echo json_encode(['ok' => true, 'rows' => $rows], JSON_UNESCAPED_SLASHES);
} catch (Throwable $e) {
    http_response_code(500);
    echo json_encode(['ok' => false, 'error' => $e->getMessage()]);
}
