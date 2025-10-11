<?php
declare(strict_types=1);

require_once __DIR__ . '/../../includes/db.php';
header('Content-Type: application/json');

try {
    $scope = strtolower($_GET['scope'] ?? 'character');
    $limit = max(1, min((int)($_GET['limit'] ?? 500), 2000));

    // UI scopes → canonical owner_type values in DB
    $SCOPE_TO_OWNERS = [
        'ship'      => ['SHIP'],
        'character' => ['SUIT','CHARACTER'],
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

    // Primary query: use view if available
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

    try {
        $stmt = db()->prepare($sql);
        $stmt->execute($params);
        $rows = $stmt->fetchAll();
    } catch (\PDOException $e) {
        // Fallback when the view doesn't exist (SQLSTATE 42S02)
        if ($e->getCode() !== '42S02') { throw $e; }

            // Fallback: view missing → query latest snapshot directly from nms_items with filters
            $snap = (int) db()->query("SELECT snapshot_id FROM nms_snapshots ORDER BY imported_at DESC LIMIT 1")->fetchColumn();
            $fallbackSql = "
                SELECT
                    resource_id,
                    SUM(amount)     AS amount,
                    MIN(item_type)  AS item_type
                FROM nms_items
                WHERE snapshot_id = ?
                  AND owner_type IN ($placeholders)
                  $invSql
                GROUP BY resource_id
                ORDER BY amount DESC
                LIMIT $limit
            ";
            $stmt = db()->prepare($fallbackSql);
            $stmt->execute(array_merge([$snap], $params));
            $rows = $stmt->fetchAll();

    }
        // If the active-root view returned no rows, retry using nms_items on latest snapshot
        if (!$rows || count($rows) === 0) {
            $snap = (int) db()->query("SELECT snapshot_id FROM nms_snapshots ORDER BY imported_at DESC LIMIT 1")->fetchColumn();
            if ($snap) {
                $fallbackSql = "
                    SELECT
                        resource_id,
                        SUM(amount)     AS amount,
                        MIN(item_type)  AS item_type
                    FROM nms_items
                    WHERE snapshot_id = ?
                      AND owner_type IN ($placeholders)
                      $invSql
                    GROUP BY resource_id
                    ORDER BY amount DESC
                    LIMIT $limit
                ";
                $stmt2 = db()->prepare($fallbackSql);
                $stmt2->execute(array_merge([$snap], $params));
                $rows2 = $stmt2->fetchAll();
                if ($rows2 && count($rows2) > 0) {
                    $rows = $rows2;
                }
            }
        }
        // Last resort: if still empty, surface UNKNOWN-owner rows so the UI isn't blank
        if (!$rows || count($rows) === 0) {
            $snap = (int) db()->query("SELECT snapshot_id FROM nms_snapshots ORDER BY imported_at DESC LIMIT 1")->fetchColumn();
            if ($snap) {
                $unkSql = "
                    SELECT
                        resource_id,
                        SUM(amount)     AS amount,
                        MIN(item_type)  AS item_type
                    FROM nms_items
                    WHERE snapshot_id = ?
                      AND owner_type = 'UNKNOWN'
                      $invSql
                    GROUP BY resource_id
                    ORDER BY amount DESC
                    LIMIT $limit
                ";
                $params3 = [$snap];
                // If ?inv=GENERAL|TECHONLY|CARGO was provided, pass it through
                if ($inv && in_array($inv, $invAllowed, true)) {
                    $params3[] = $inv;
                }
                $stmt3 = db()->prepare($unkSql);
                $stmt3->execute($params3);
                $rows3 = $stmt3->fetchAll();
                if ($rows3 && count($rows3) > 0) {
                    $rows = $rows3;
                }
            }
        }

        echo json_encode(['ok' => true, 'rows' => $rows], JSON_UNESCAPED_SLASHES);
    } catch (Throwable $e) {
        http_response_code(500);
        echo json_encode(['ok' => false, 'error' => $e->getMessage()]);
    }
