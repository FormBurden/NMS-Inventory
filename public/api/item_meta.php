<?php
declare(strict_types=1);
header('Content-Type: application/json; charset=utf-8');

$rid = $_GET['search'] ?? $_GET['id'] ?? '';
$rid = urldecode($rid);
$rid = ltrim($rid, '^');
$rid = strtoupper(trim($rid));

$path = __DIR__ . '/../data/items_local.json';
if (!file_exists($path)) {
    http_response_code(500);
    echo json_encode(['ok' => false, 'error' => 'items_local.json missing', 'path' => $path]);
    exit;
}

$data = json_decode(file_get_contents($path), true);
if (!is_array($data)) {
    http_response_code(500);
    echo json_encode(['ok' => false, 'error' => 'items_local.json invalid']);
    exit;
}

$entry = $data[$rid] ?? null;
if (!$entry) {
    echo json_encode(['ok' => true, 'found' => false, 'rid' => $rid]);
    exit;
}

echo json_encode([
    'ok'    => true,
    'found' => true,
    'rid'   => $rid,
    'name'  => $entry['name'] ?? $rid,
    'kind'  => $entry['kind'] ?? null,
    'icon'  => $entry['icon'] ?? null,
    'appId' => $entry['appId'] ?? null,
]);
