<?php
declare(strict_types=1);

require_once __DIR__ . '/../../includes/db.php';
if (is_file(__DIR__ . '/../../includes/bootstrap.php')) require_once __DIR__ . '/../../includes/bootstrap.php';
header('Content-Type: application/json; charset=utf-8');

function db(): PDO {
    if (function_exists('get_db')) return get_db();
    global $pdo;
    if ($pdo instanceof PDO) return $pdo;
    http_response_code(500);
    echo json_encode(['ok' => false, 'error' => 'DB not initialized'], JSON_UNESCAPED_SLASHES);
    exit;
}

function jexit($d, int $c = 200): void {
    http_response_code($c);
    echo json_encode($d, JSON_UNESCAPED_SLASHES);
    exit;
}

function read_snapshot_ts(): ?string {
    $p = realpath(__DIR__ . '/../../storage/decoded/_manifest_recent.json');
    if (!$p || !is_file($p)) return null;

    $s = @file_get_contents($p);
    if ($s === false) return null;

    $o = json_decode($s, true);
    if (!is_array($o)) return null;

    if (!empty($o['snapshot_ts']) && is_string($o['snapshot_ts'])) {
        return $o['snapshot_ts'];
    }

    $it = $o['items'][0] ?? null;
    return (is_array($it) && !empty($it['source_mtime'])) ? (string)$it['source_mtime'] : null;
}

function view_exists(PDO $pdo, string $name): bool {
    $q = "SELECT 1 FROM information_schema.VIEWS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :n LIMIT 1";
    $st = $pdo->prepare($q);
    if (!$st) return false;

    return $st->execute([':n' => $name]) && (bool)$st->fetchColumn();
}

function request_bool(string $camelName, string $snakeName, string $default = '0'): bool {
    $value = $_GET[$camelName] ?? $_GET[$snakeName] ?? $default;
    $value = strtolower(trim((string)$value));

    return in_array($value, ['1', 'true', 'yes', 'on'], true);
}

function normalize_item_id(string $value): string {
    $value = strtoupper(trim($value));
    $value = ltrim($value, '^');

    $hash = strpos($value, '#');
    if ($hash !== false) {
        $value = substr($value, 0, $hash);
    }

    return $value;
}

function catalogue_candidates(string $value): array {
    $base = normalize_item_id($value);
    if ($base === '') return [];

    $candidates = [$base];

    if (str_starts_with($base, 'T_')) {
        $candidates[] = substr($base, 2);
    } else {
        $candidates[] = 'T_' . $base;
    }

    if (str_starts_with($base, 'U_')) {
        $core = substr($base, 2);
        $candidates[] = $core;
        $candidates[] = 'UT_' . $core;
    }

    if (str_starts_with($base, 'UP_')) {
        $core = substr($base, 3);
        $candidates[] = $core;
        $candidates[] = 'UT_' . $core;
    }

    if (str_starts_with($base, 'UT_')) {
        $candidates[] = substr($base, 3);
    }

    $strippedDigit = preg_replace('/[0-9]+$/', '', $base);
    if (is_string($strippedDigit) && $strippedDigit !== '' && $strippedDigit !== $base) {
        $candidates[] = $strippedDigit;
    }

    $out = [];
    $seen = [];
    foreach ($candidates as $candidate) {
        $candidate = strtoupper(trim((string)$candidate));
        if ($candidate === '' || isset($seen[$candidate])) continue;

        $seen[$candidate] = true;
        $out[] = $candidate;
    }

    return $out;
}

function load_catalogue(): array {
    $candidates = [
        __DIR__ . '/../data/items_local.json',
        __DIR__ . '/../assets/items_local.json',
        __DIR__ . '/../icons/items_local.json',
        __DIR__ . '/../Inventory/assets/items_local.json',
        __DIR__ . '/../Inventory/data/items_local.json',
        __DIR__ . '/../Inventory/items_local.json',
    ];

    foreach ($candidates as $p) {
        if (!is_file($p)) continue;

        $raw = @file_get_contents($p);
        if ($raw === false) continue;

        $arr = json_decode($raw, true);
        if (is_array($arr)) return $arr;
    }

    return [];
}

function resolve_scope_filter(string $scope): array {
    $scope = strtolower(trim($scope));

    if ($scope === '' || $scope === 'all') {
        return [];
    }

    $aliases = [
        'character' => ['character'],
        'exosuit' => ['character'],
        'suit' => ['character'],

        'ship' => ['ship'],
        'starship' => ['ship'],

        'corvette' => ['character', 'ship'],

        'vehicle' => ['vehicle'],
        'vehicles' => ['vehicle'],
        'exocraft' => ['vehicle'],

        'freighter' => ['freighter'],
        'frigate' => ['freighter'],

        'storage' => ['storage'],
        'base' => [],
    ];

    if (isset($aliases[$scope])) {
        return $aliases[$scope];
    }

    $scopes = array_values(array_filter(array_map('trim', explode(',', $scope))));
    $out = [];
    $seen = [];

    foreach ($scopes as $item) {
        foreach (($aliases[$item] ?? [$item]) as $resolved) {
            if ($resolved === '' || isset($seen[$resolved])) continue;

            $seen[$resolved] = true;
            $out[] = $resolved;
        }
    }

    return $out;
}

function scope_where_clause(array $resolvedScopes, array &$params, string $prefix = 'scope'): string {
    if (!$resolvedScopes) {
        return '';
    }

    $placeholders = [];

    foreach ($resolvedScopes as $index => $scope) {
        $scope = strtolower(trim((string)$scope));
        if ($scope === '') continue;

        $key = ":{$prefix}_owner_{$index}";
        $placeholders[] = $key;
        $params[$key] = $scope;
    }

    if (!$placeholders) {
        return '';
    }

    return 'WHERE LOWER(owner_type) IN (' . implode(',', $placeholders) . ')';
}

function virtual_scope_name(string $scope): string {
    $scope = strtolower(trim($scope));

    if (in_array($scope, ['corvette', 'base'], true)) {
        return $scope;
    }

    return '';
}

function catalogue_lookup(array $catalogue, string $resourceId): ?array {
    foreach (catalogue_candidates($resourceId) as $candidate) {
        if (isset($catalogue[$candidate]) && is_array($catalogue[$candidate])) {
            $row = $catalogue[$candidate];
            $row['_catalogue_key'] = $candidate;
            return $row;
        }
    }

    return null;
}

function icon_url_for_row(string $resourceId, ?string $kind): string {
    $baseId = normalize_item_id($resourceId);
    $query = http_build_query(array_filter([
        'id' => $baseId,
        'type' => is_string($kind) && trim($kind) !== '' ? trim($kind) : null,
    ], static fn($value) => $value !== null && $value !== ''));

    return '/api/icon.php?' . $query;
}

function enrich_inventory_rows(array $rows, array $catalogue): array {
    foreach ($rows as &$row) {
        if (!is_array($row)) continue;

        $resourceId = (string)($row['resource_id'] ?? '');
        $baseId = normalize_item_id($resourceId);
        $meta = catalogue_lookup($catalogue, $resourceId);

        $row['base_id'] = $baseId;

        if (is_array($meta)) {
            $kind = $meta['kind'] ?? null;

            $row['catalogue_id'] = (string)($meta['id'] ?? $meta['_catalogue_key'] ?? $baseId);
            $row['display_name'] = (string)($meta['name'] ?? $row['catalogue_id']);
            $row['kind'] = $kind;
            $row['icon_url'] = icon_url_for_row($resourceId, is_string($kind) ? $kind : null);
            $row['source_icon_url'] = is_string($meta['icon'] ?? null) ? $meta['icon'] : null;
            $row['appId'] = $meta['appId'] ?? null;
            $row['category'] = is_string($meta['category'] ?? null) ? $meta['category'] : null;
            $row['group'] = is_string($meta['group'] ?? null) ? $meta['group'] : null;
            $row['tags'] = array_values(array_filter((array)($meta['tags'] ?? []), static fn($tag): bool => is_string($tag) && trim($tag) !== ''));

            if (array_key_exists('aliasOf', $meta)) {
                $row['aliasOf'] = $meta['aliasOf'];
            }

            if (array_key_exists('synthetic', $meta)) {
                $row['synthetic'] = (bool)$meta['synthetic'];
            }
        } else {
            $kind = is_string($row['kind'] ?? null) ? (string)$row['kind'] : null;

            $row['catalogue_id'] = $baseId;
            $row['display_name'] = $baseId !== '' ? $baseId : $resourceId;
            $row['kind'] = $kind;
            $row['icon_url'] = icon_url_for_row($resourceId, $kind);
            $row['source_icon_url'] = null;
            $row['category'] = null;
            $row['group'] = null;
            $row['tags'] = [];
        }
    }
    unset($row);

    return $rows;
}

function session_id_from_started_at(?string $startedAt): string {
    if (!is_string($startedAt) || trim($startedAt) === '') {
        return '';
    }

    return preg_replace('/[^0-9]/', '', $startedAt) ?: '';
}

function read_process_session_state(): array {
    $path = realpath(__DIR__ . '/../../storage/runtime/nms_session.env');
    if (!$path || !is_file($path)) {
        return [
            'id' => '',
            'active' => false,
            'started_at' => null,
            'ended_at' => null,
            'pids' => '',
            'updated_at' => null,
            'source' => 'missing',
            'label' => 'No recorded session',
        ];
    }

    $lines = @file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    if ($lines === false) {
        return [
            'id' => '',
            'active' => false,
            'started_at' => null,
            'ended_at' => null,
            'pids' => '',
            'updated_at' => null,
            'source' => 'unreadable',
            'label' => 'No recorded session',
        ];
    }

    $values = [];
    foreach ($lines as $line) {
        if (strpos($line, '=') === false) continue;

        [$key, $value] = explode('=', $line, 2);
        $values[strtoupper(trim($key))] = trim($value);
    }

    $startedAt = ($values['STARTED_AT'] ?? '') !== '' ? $values['STARTED_AT'] : null;
    $endedAt = ($values['ENDED_AT'] ?? '') !== '' ? $values['ENDED_AT'] : null;
    $active = ($values['ACTIVE'] ?? '0') === '1';

    return [
        'id' => session_id_from_started_at($startedAt),
        'active' => $active,
        'started_at' => $startedAt,
        'ended_at' => $endedAt,
        'pids' => $values['PIDS'] ?? '',
        'updated_at' => ($values['UPDATED_AT'] ?? '') !== '' ? $values['UPDATED_AT'] : null,
        'source' => 'process',
        'label' => session_label($startedAt, $endedAt, $active),
    ];
}

function session_label(?string $startedAt, ?string $endedAt, bool $active): string {
    if (!is_string($startedAt) || trim($startedAt) === '') {
        return 'No recorded session';
    }

    if ($active) {
        return $startedAt . ' — current';
    }

    if (is_string($endedAt) && trim($endedAt) !== '') {
        return $startedAt . ' — ' . $endedAt;
    }

    return $startedAt;
}

function read_recent_sessions(array $processSession, int $limit = 5): array {
    $limit = max(1, min(20, $limit));
    $sessions = [];
    $seen = [];

    if (
        ($processSession['active'] ?? false) === true &&
        is_string($processSession['started_at'] ?? null) &&
        $processSession['started_at'] !== ''
    ) {
        $id = (string)($processSession['id'] ?? session_id_from_started_at($processSession['started_at']));
        if ($id !== '') {
            $sessions[] = [
                'id' => $id,
                'active' => true,
                'started_at' => $processSession['started_at'],
                'ended_at' => null,
                'source' => 'process',
                'label' => session_label($processSession['started_at'], null, true),
            ];
            $seen[$id] = true;
        }
    }

    $path = realpath(__DIR__ . '/../../storage/runtime/nms_sessions.tsv');
    if ($path && is_file($path)) {
        $lines = @file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
        if (is_array($lines)) {
            $records = [];

            foreach ($lines as $index => $line) {
                if ($index === 0 && str_starts_with($line, 'session_id')) {
                    continue;
                }

                $parts = explode("\t", $line);
                if (count($parts) < 4) {
                    continue;
                }

                [$id, $startedAt, $endedAt, $status] = $parts;
                $id = trim($id);
                $startedAt = trim($startedAt);
                $endedAt = trim($endedAt);

                if ($id === '' || $startedAt === '' || $endedAt === '') {
                    continue;
                }

                if (isset($seen[$id])) {
                    continue;
                }

                $records[] = [
                    'id' => $id,
                    'active' => false,
                    'started_at' => $startedAt,
                    'ended_at' => $endedAt,
                    'source' => 'history',
                    'label' => session_label($startedAt, $endedAt, false),
                ];
            }

            usort($records, static function (array $a, array $b): int {
                return strcmp((string)$b['started_at'], (string)$a['started_at']);
            });

            foreach ($records as $record) {
                if (count($sessions) >= $limit) {
                    break;
                }

                $sessions[] = $record;
                $seen[(string)$record['id']] = true;
            }
        }
    }

    return array_slice($sessions, 0, $limit);
}

function select_recent_session(array $sessions, string $requestedId): ?array {
    $requestedId = trim($requestedId);

    if ($requestedId !== '') {
        foreach ($sessions as $session) {
            if (is_array($session) && (string)($session['id'] ?? '') === $requestedId) {
                return $session;
            }
        }
    }

    foreach ($sessions as $session) {
        if (is_array($session) && ($session['active'] ?? false) === true) {
            return $session;
        }
    }

    return $sessions[0] ?? null;
}


function filter_virtual_scope_rows(array $rows, string $virtualScope): array {
    if ($virtualScope === '') {
        return $rows;
    }

    if ($virtualScope === 'corvette') {
        return array_values(array_filter($rows, static function ($row): bool {
            if (!is_array($row)) return false;

            $baseId = strtoupper((string)($row['base_id'] ?? ''));
            return str_starts_with($baseId, 'CV_');
        }));
    }

    if ($virtualScope === 'base') {
        return array_values(array_filter($rows, static function ($row): bool {
            if (!is_array($row)) return false;

            $baseId = strtoupper((string)($row['base_id'] ?? ''));
            $kind = strtolower(trim((string)($row['kind'] ?? '')));

            if ($kind === 'building') {
                return true;
            }

            if (str_starts_with($baseId, 'B_')) {
                return true;
            }

            if (str_starts_with($baseId, 'BASE_')) {
                return true;
            }

            if (str_starts_with($baseId, 'BUILD')) {
                return true;
            }

            if (str_starts_with($baseId, 'CONTAINER')) {
                return true;
            }

            if (str_starts_with($baseId, 'FRE_ROOM_')) {
                return true;
            }

            if (str_starts_with($baseId, 'GARAGE_')) {
                return true;
            }

            return false;
        }));
    }

    return $rows;
}

try {
    $pdo = db();
    $limit = max(1, min(1000, (int)($_GET['limit'] ?? 500)));
    $offset = max(0, (int)($_GET['offset'] ?? 0));
    $includeTech = request_bool('includeTech', 'include_tech');
    $sort = strtolower((string)($_GET['sort'] ?? ''));
    $scope = (string)($_GET['scope'] ?? 'ALL');
    $snapshotTs = read_snapshot_ts();
    $catalogue = load_catalogue();
    $processSession = read_process_session_state();
    $sessions = read_recent_sessions($processSession, 5);
    $selectedSession = select_recent_session($sessions, (string)($_GET['session_id'] ?? ''));

    $params = [];
    $resolvedScopes = resolve_scope_filter($scope);
    $virtualScope = virtual_scope_name($scope);
    $where = scope_where_clause($resolvedScopes, $params);

    $haveActive = view_exists($pdo, 'v_api_inventory_rows_active');
    $haveRecent = view_exists($pdo, 'v_api_inventory_rows_recent');
    $useRecent = ($sort === 'recent') && $haveRecent;

    if ($sort === 'ledger_session' || $sort === 'session_changes') {
        $sessionWhere = 'WHERE 1 = 0';

        if (
            is_array($selectedSession) &&
            is_string($selectedSession['started_at'] ?? null) &&
            $selectedSession['started_at'] !== ''
        ) {
            $sessionWhere = 'WHERE computed_at >= :session_started_at';
            $params[':session_started_at'] = $selectedSession['started_at'];

            if (
                ($selectedSession['active'] ?? false) === false &&
                is_string($selectedSession['ended_at'] ?? null) &&
                $selectedSession['ended_at'] !== ''
            ) {
                $sessionWhere .= ' AND computed_at <= :session_ended_at';
                $params[':session_ended_at'] = $selectedSession['ended_at'];
            }
        }

        $sql = "
          SELECT d.from_snapshot_id,
                 d.to_snapshot_id,
                 d.resource_id,
                 d.delta AS amount,
                 d.delta,
                 d.computed_at,
                 COALESCE(i.owner_type, '') AS owner_type,
                 COALESCE(i.inventory, '') AS inventory
            FROM (
                  SELECT MIN(from_snapshot_id) AS from_snapshot_id,
                         MAX(to_snapshot_id) AS to_snapshot_id,
                         resource_id,
                         SUM(delta) AS delta,
                         MAX(computed_at) AS computed_at
                    FROM nms_ledger_deltas
                    $sessionWhere
                GROUP BY resource_id
                  HAVING SUM(delta) <> 0
             ) d
       LEFT JOIN (
                  SELECT resource_id,
                         MIN(owner_type) AS owner_type,
                         MIN(inventory) AS inventory
                    FROM nms_items
                   WHERE snapshot_id = (
                         SELECT MAX(snapshot_id)
                           FROM nms_snapshots
                     )
                GROUP BY resource_id
             ) i
              ON i.resource_id = d.resource_id
        ORDER BY d.computed_at DESC, ABS(d.delta) DESC, d.resource_id
           LIMIT :limit OFFSET :offset";
    } elseif ($sort === 'ledger' || $sort === 'recent_changes') {
        $sql = "
          SELECT d.from_snapshot_id,
                 d.to_snapshot_id,
                 d.resource_id,
                 d.delta AS amount,
                 d.delta,
                 d.computed_at,
                 COALESCE(i.owner_type, '') AS owner_type,
                 COALESCE(i.inventory, '') AS inventory
            FROM (
                  SELECT MIN(from_snapshot_id) AS from_snapshot_id,
                         MAX(to_snapshot_id) AS to_snapshot_id,
                         resource_id,
                         SUM(delta) AS delta,
                         MAX(computed_at) AS computed_at
                    FROM nms_ledger_deltas
                   WHERE to_snapshot_id = (
                         SELECT MAX(to_snapshot_id)
                           FROM nms_ledger_deltas
                     )
                GROUP BY resource_id
                  HAVING SUM(delta) <> 0
             ) d
       LEFT JOIN (
                  SELECT resource_id,
                         MIN(owner_type) AS owner_type,
                         MIN(inventory) AS inventory
                    FROM nms_items
                   WHERE snapshot_id = (
                         SELECT MAX(snapshot_id)
                           FROM nms_snapshots
                     )
                GROUP BY resource_id
             ) i
              ON i.resource_id = d.resource_id
        ORDER BY d.computed_at DESC, ABS(d.delta) DESC, d.resource_id
           LIMIT :limit OFFSET :offset";
    } elseif (!$includeTech) {
        $ownerFilter = $where ? preg_replace('/^WHERE\s+/i', 'AND ', $where) : '';
        $sql = "
          SELECT owner_type, inventory, resource_id, SUM(amount) AS amount
            FROM nms_items
           WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM nms_snapshots)
             AND UPPER(inventory) NOT IN ('TECH', 'TECHNOLOGY')
             AND COALESCE(UPPER(item_type), '') NOT IN ('TECH', 'TECHNOLOGY')
             $ownerFilter
        GROUP BY owner_type, inventory, resource_id
        ORDER BY owner_type, inventory, resource_id
           LIMIT :limit OFFSET :offset";
    } elseif ($useRecent) {
        $sql = "
          SELECT owner_type, inventory, resource_id, amount
            FROM v_api_inventory_rows_recent
            " . ($where ?: '') . "
        ORDER BY recent_ts DESC, owner_type, inventory, resource_id
           LIMIT :limit OFFSET :offset";
    } elseif ($haveActive) {
        $sql = "
          SELECT owner_type, inventory, resource_id, amount
            FROM v_api_inventory_rows_active
            " . ($where ?: '') . "
        ORDER BY owner_type, inventory, resource_id
           LIMIT :limit OFFSET :offset";
    } else {
        $ownerFilter = $where ? preg_replace('/^WHERE\s+/i', 'AND ', $where) : '';
        $sql = "
          SELECT owner_type, inventory, resource_id, SUM(amount) AS amount
            FROM nms_items
           WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM nms_snapshots)
             $ownerFilter
        GROUP BY owner_type, inventory, resource_id
        ORDER BY owner_type, inventory, resource_id
           LIMIT :limit OFFSET :offset";
    }

    $st = $pdo->prepare($sql);
    if (!$st) throw new RuntimeException('Prepare failed');

    foreach ($params as $k => $v) {
        $st->bindValue($k, $v, PDO::PARAM_STR);
    }

    $st->bindValue(':limit', $limit, PDO::PARAM_INT);
    $st->bindValue(':offset', $offset, PDO::PARAM_INT);

    if (!$st->execute()) throw new RuntimeException('Execute failed');

    $rows = $st->fetchAll(PDO::FETCH_ASSOC) ?: [];
    $rows = enrich_inventory_rows($rows, $catalogue);
    $rows = filter_virtual_scope_rows($rows, $virtualScope);

    jexit([
        'ok' => true,
        'snapshot_ts' => $snapshotTs,
        'include_tech' => $includeTech,
        'catalogue_loaded' => $catalogue !== [],
        'requested_scope' => $scope,
        'resolved_scopes' => $resolvedScopes,
        'virtual_scope' => $virtualScope,
        'view' => in_array($sort, ['ledger', 'recent_changes', 'ledger_session', 'session_changes'], true) ? 'recent' : 'inventory',
        'session' => $selectedSession ?: $processSession,
        'sessions' => $sessions,
        'rows' => $rows,
    ]);
} catch (Throwable $e) {
    jexit(['ok' => false, 'error' => 'Query failed', 'detail' => $e->getMessage()], 500);
}