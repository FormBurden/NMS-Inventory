<?php
declare(strict_types=1);

/**
 * Icon resolver.
 * Priority: direct URL → icon_map candidates → items_local.json → local file → placeholder.
 * Remote icons are proxied and cached so the browser stays on localhost.
 */
header('Cache-Control: public, max-age=86400');

$placeholder = __DIR__ . '/../../assets/img/placeholder.png';
$cacheDir = __DIR__ . '/../../cache/icons';

function set_diag(string $v): void {
    header('X-Icon-Resolver: ' . $v);
}

function is_head_request(): bool {
    return strtoupper((string)($_SERVER['REQUEST_METHOD'] ?? 'GET')) === 'HEAD';
}

function emit_file(string $p, string $type = 'image/png', int $code = 200): never {
    if (!is_file($p)) {
        http_response_code(404);
        exit;
    }

    http_response_code($code);
    header('Content-Type: ' . $type);
    header('Content-Length: ' . (string)filesize($p));

    if (!is_head_request()) {
        readfile($p);
    }
    exit;
}

function normalize_resource_id(string $rid): string {
    $rid = strtoupper(trim($rid));
    if ($rid !== '' && $rid[0] === '^') {
        $rid = substr($rid, 1);
    }

    $hashPos = strpos($rid, '#');
    if ($hashPos !== false) {
        $rid = substr($rid, 0, $hashPos);
    }

    return $rid;
}

function safe_remote_url(string $u): bool {
    if (!preg_match('~^https?://~i', $u)) return false;
    $host = strtolower((string)(parse_url($u, PHP_URL_HOST) ?? ''));
    return $host !== '';
}

function fetch_remote_icon(string $u): ?array {
    if (!safe_remote_url($u)) return null;

    $type = '';
    if (function_exists('curl_init')) {
        $ch = curl_init($u);
        if ($ch === false) return null;

        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_FOLLOWLOCATION => true,
            CURLOPT_MAXREDIRS => 8,
            CURLOPT_CONNECTTIMEOUT => 8,
            CURLOPT_TIMEOUT => 20,
            CURLOPT_USERAGENT => 'Mozilla/5.0 NMS-Inventory/1.0',
            CURLOPT_HEADER => false,
        ]);

        $body = curl_exec($ch);
        $code = (int)curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        $type = (string)curl_getinfo($ch, CURLINFO_CONTENT_TYPE);
        curl_close($ch);

        if (!is_string($body) || $body === '' || $code < 200 || $code >= 300) {
            return null;
        }
    } else {
        $ctx = stream_context_create([
            'http' => [
                'follow_location' => 1,
                'max_redirects' => 8,
                'timeout' => 20,
                'header' => "User-Agent: Mozilla/5.0 NMS-Inventory/1.0\r\n",
            ],
        ]);

        $body = @file_get_contents($u, false, $ctx);
        if (!is_string($body) || $body === '') {
            return null;
        }

        foreach (($http_response_header ?? []) as $header) {
            if (stripos($header, 'Content-Type:') === 0) {
                $type = trim(substr($header, strlen('Content-Type:')));
                break;
            }
        }
    }

    $type = strtolower(trim(explode(';', $type)[0] ?? ''));
    if (!in_array($type, ['image/png', 'image/jpeg', 'image/gif', 'image/webp'], true)) {
        return null;
    }

    return ['body' => $body, 'type' => $type];
}

function emit_remote_icon(string $u, string $source, string $cacheDir): bool {
    if (!is_dir($cacheDir)) {
        @mkdir($cacheDir, 0775, true);
    }
    if (!is_dir($cacheDir)) {
        return false;
    }

    $key = hash('sha256', $u);
    $bin = $cacheDir . '/' . $key . '.bin';
    $meta = $cacheDir . '/' . $key . '.json';

    if (is_file($bin) && is_file($meta)) {
        $raw = @file_get_contents($meta);
        $m = is_string($raw) ? json_decode($raw, true) : null;
        $type = is_array($m) ? (string)($m['content_type'] ?? 'image/png') : 'image/png';
        set_diag($source . ':cache');
        emit_file($bin, $type);
    }

    $fetched = fetch_remote_icon($u);
    if (!$fetched) {
        return false;
    }

    if (@file_put_contents($bin, $fetched['body']) === false) {
        return false;
    }

    @file_put_contents($meta, json_encode([
        'url' => $u,
        'content_type' => $fetched['type'],
    ], JSON_UNESCAPED_SLASHES));

    set_diag($source . ':proxy');
    emit_file($bin, $fetched['type']);
}

function emit_first_remote_icon(array $urls, string $source, string $cacheDir): bool {
    foreach ($urls as $u) {
        $u = (string)$u;
        if ($u !== '' && preg_match('~^https?://~i', $u) && emit_remote_icon($u, $source, $cacheDir)) {
            return true;
        }
    }
    return false;
}

function icon_map_candidates(string $rid, string $type): array {
    $mapPath = realpath(__DIR__ . '/../../includes/icon_map.php');
    if (!$mapPath || !is_file($mapPath)) {
        return [];
    }

    require_once $mapPath;

    if (function_exists('nms_icon_candidates')) {
        $out = nms_icon_candidates($rid, $type);
        return is_array($out) ? $out : [];
    }

    if (function_exists('nms_icon_for_id')) {
        return [(string)nms_icon_for_id($rid)];
    }

    if (function_exists('nms_icon_url')) {
        return [(string)nms_icon_url($rid, $type)];
    }

    return [];
}

$inUrl = trim((string)($_GET['url'] ?? ''));
if ($inUrl !== '' && emit_remote_icon($inUrl, 'direct-url', $cacheDir)) {
    exit;
}

$rawRid = (string)($_GET['id'] ?? $_GET['rid'] ?? $_GET['resource_id'] ?? '');
$rid = normalize_resource_id($rawRid);
$type = trim((string)($_GET['type'] ?? ''));

if ($rid !== '') {
    $urls = icon_map_candidates($rid, $type);
    if (emit_first_remote_icon($urls, 'icon_map:url', $cacheDir)) {
        exit;
    }

    foreach ($urls as $u) {
        $u = (string)$u;
        if ($u === '' || preg_match('~^https?://~i', $u)) {
            continue;
        }

        $local = realpath(__DIR__ . '/../' . ltrim($u, '/'));
        if ($local && is_file($local)) {
            set_diag('icon_map:local');
            emit_file($local);
        }
    }
}

if ($rid !== '') {
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
        $arr = $raw !== false ? json_decode($raw, true) : null;
        if (!is_array($arr)) continue;

        foreach ($arr as $row) {
            if (!is_array($row)) continue;

            $id = normalize_resource_id((string)($row['resource_id'] ?? $row['id'] ?? ''));
            if ($id !== $rid) continue;

            $u = (string)($row['icon_url'] ?? $row['icon'] ?? '');
            if ($u !== '') {
                if (preg_match('~^https?://~i', $u) && emit_remote_icon($u, 'items_json:url', $cacheDir)) {
                    exit;
                }

                $local = realpath(__DIR__ . '/../' . ltrim($u, '/'));
                if ($local && is_file($local)) {
                    set_diag('items_json:local');
                    emit_file($local);
                }
            }

            break 2;
        }
    }
}

if ($rid !== '') {
    $byId = __DIR__ . '/../icons/' . $rid . '.png';
    if (is_file($byId)) {
        set_diag('icons/<ID>.png');
        emit_file($byId);
    }
}

set_diag('placeholder');
emit_file($placeholder, 'image/png', 200);