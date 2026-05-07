<?php
declare(strict_types=1);
header('Content-Type: application/json; charset=utf-8');

function jexit($data,int $code=200){ http_response_code($code); echo json_encode($data, JSON_UNESCAPED_SLASHES); exit; }
function set_diag(string $v): void { header('X-Meta-Resolver: '.$v); }

$q  = $_GET['search'] ?? $_GET['name'] ?? '';
$id = $_GET['id'] ?? $_GET['rid'] ?? $_GET['resource_id'] ?? '';

$q  = strtoupper(trim((string)$q));
$id = strtoupper(trim((string)$id));
if ($q === '' && $id === '') jexit(['ok'=>false,'error'=>'Missing id or search'], 400);

$candidates = [
    __DIR__ . '/../data/items_local.json',
    __DIR__ . '/../assets/items_local.json',
    __DIR__ . '/../icons/items_local.json',
    __DIR__ . '/../Inventory/assets/items_local.json',
    __DIR__ . '/../Inventory/data/items_local.json',
    __DIR__ . '/../Inventory/items_local.json',
];

$items = null;
foreach ($candidates as $p) {
    if (!is_file($p)) continue;
    $raw = @file_get_contents($p);
    $arr = $raw !== false ? json_decode($raw, true) : null;
    if (is_array($arr)) { $items = $arr; set_diag('items_json:'.$p); break; }
}
if (!is_array($items)) jexit(['ok'=>false,'error'=>'items_local.json not found or invalid'], 500);

function normalize_item_id(string $value): string {
    $value = strtoupper(trim($value));
    $value = ltrim($value, '^');
    $hash = strpos($value, '#');
    if ($hash !== false) $value = substr($value, 0, $hash);
    return $value;
}

$meta = null;
$lookupId = normalize_item_id($id);

if ($lookupId !== '' && isset($items[$lookupId]) && is_array($items[$lookupId])) {
    $meta = $items[$lookupId];
} else {
    foreach ($items as $key => $row) {
        if (!is_array($row)) continue;

        $keyId = normalize_item_id((string)$key);
        $rowId = normalize_item_id((string)($row['id'] ?? $row['resource_id'] ?? ''));
        $nm = strtoupper((string)($row['name'] ?? ''));

        if ($lookupId !== '' && ($keyId === $lookupId || $rowId === $lookupId)) {
            $meta = $row;
            break;
        }

        if ($q !== '' && $q !== '^' && str_starts_with($nm, ltrim($q, '^'))) {
            $meta = $row;
            break;
        }
    }
}

if (!$meta) jexit(['ok'=>false,'error'=>'Not found','query'=>$id ?: $q], 404);
jexit(['ok'=>true,'item'=>$meta]);
