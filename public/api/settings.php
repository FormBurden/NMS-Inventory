<?php
declare(strict_types=1);

// Keep these requires as-is to match your project wiring:
require_once __DIR__ . '/../../includes/db.php';
require_once __DIR__ . '/../../includes/bootstrap.php';

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

const TABLE = 'nms_settings';
const DEFAULTS = [
  'language'       => 'en-us',
  'defaultWindow'  => 'Character',
  'iconSize'       => 'medium',   // small | medium | large
  'showNegatives'  => true,
  'autoRefreshSec' => 15,         // 0=off
  'theme'          => 'system',   // light | dark | system
  'recentFirst'   => false,
];

function json_out($data, int $code = 200): void {
  http_response_code($code);
  echo json_encode($data, JSON_UNESCAPED_SLASHES);
  exit;
}

try {
  $pdo = db(); // your includes/db.php should expose this (PDO with ERRMODE_EXCEPTION)

  // Create table if missing (no CHECK constraints for max MariaDB compatibility)
  $pdo->exec("
    CREATE TABLE IF NOT EXISTS `".TABLE."` (
      `id` TINYINT UNSIGNED NOT NULL PRIMARY KEY,
      `settings_json` LONGTEXT NOT NULL,
      `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  ");

  // Ensure row id=1 exists
  $pdo->exec("INSERT IGNORE INTO `".TABLE."` (`id`,`settings_json`) VALUES (1, '{}')");

  $method = $_SERVER['REQUEST_METHOD'] ?? 'GET';

  if ($method === 'GET') {
    $row = $pdo->query("SELECT settings_json FROM `".TABLE."` WHERE id=1")->fetch(PDO::FETCH_ASSOC);
    $stored = [];
    if ($row && !empty($row['settings_json'])) {
      $dec = json_decode($row['settings_json'], true);
      if (is_array($dec)) $stored = $dec;
    }
    $merged = array_replace(DEFAULTS, $stored);
    json_out(['ok' => true, 'settings' => $merged]);
    return;
  }

  if ($method === 'POST') {
    $raw = file_get_contents('php://input') ?: '{}';
    $in  = json_decode($raw, true);
    if (!is_array($in)) json_out(['ok'=>false,'error'=>'Invalid JSON body'], 400);

    $allowed = array_keys(DEFAULTS);
    $clean = [];
    foreach ($allowed as $k) if (array_key_exists($k, $in)) $clean[$k] = $in[$k];

    $row = $pdo->query("SELECT settings_json FROM `".TABLE."` WHERE id=1")->fetch(PDO::FETCH_ASSOC);
    $current = [];
    if ($row && !empty($row['settings_json'])) {
      $dec = json_decode($row['settings_json'], true);
      if (is_array($dec)) $current = $dec;
    }
    $merged = array_replace(DEFAULTS, $current, $clean);
    $json = json_encode($merged, JSON_UNESCAPED_UNICODE);

    $stmt = $pdo->prepare("
      INSERT INTO `".TABLE."` (`id`,`settings_json`)
      VALUES (1, :j)
      ON DUPLICATE KEY UPDATE `settings_json` = VALUES(`settings_json`)
    ");
    $stmt->execute([':j' => $json]);

    json_out(['ok'=>true,'settings'=>$merged]);
    return;
  }

  json_out(['ok'=>false,'error'=>'Method not allowed'], 405);
} catch (Throwable $e) {
  error_log('[settings.php] '.$e->getMessage());
  json_out(['ok'=>false,'error'=>'Internal error'], 500);
}
