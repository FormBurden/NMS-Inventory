<?php
declare(strict_types=1);

$id = $_GET['id'] ?? '';
$id = urldecode($id);
$id = ltrim($id, '^');
$id = strtoupper(trim($id));

$path = __DIR__ . '/../data/items_local.json';
$placeholder = '/assets/img/placeholder.png';

if (!file_exists($path)) {
    header('Location: ' . $placeholder, true, 302);
    exit;
}

$data = json_decode(file_get_contents($path), true);
$entry = $data[$id] ?? null;
$icon  = $entry['icon'] ?? null;

// If JSON has a full URL (cdn.nmsassistant.com), just redirect there.
// <img> doesn’t require CORS, so this works fine in the browser.
if ($icon && filter_var($icon, FILTER_VALIDATE_URL)) {
    header('Location: ' . $icon, true, 302);
    exit;
}

// Optional: serve a local icon if you drop one into public/icons/ID.png
$local = __DIR__ . '/../icons/' . $id . '.png';
if (file_exists($local)) {
    header('Content-Type: image/png');
    readfile($local);
    exit;
}

// Fallback
header('Location: ' . $placeholder, true, 302);
