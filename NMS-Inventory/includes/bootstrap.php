<?php
// Very small bootstrap (EDTB-style, no framework)
$env = [];
$envPath = __DIR__ . '/../.env';
if (file_exists($envPath)) {
  foreach (file($envPath, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
    if (str_starts_with(trim($line), '#')) continue;
    if (!str_contains($line, '=')) continue;
    [$k, $v] = explode('=', $line, 2);
    $env[trim($k)] = trim($v);
  }
} else {
  // Fall back to .env.example
  foreach (file(__DIR__ . '/../.env.example', FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
    if (str_starts_with(trim($line), '#')) continue;
    if (!str_contains($line, '=')) continue;
    [$k, $v] = explode('=', $line, 2);
    $env[trim($k)] = trim($v);
  }
}

function env($k, $default=null) {
  global $env; return $env[$k] ?? $default;
}

require_once __DIR__ . '/db.php';
require_once __DIR__ . '/icon_map.php';
