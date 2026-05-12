<?php
declare(strict_types=1);

if (is_file(__DIR__ . '/../../includes/bootstrap.php')) require_once __DIR__ . '/../../includes/bootstrap.php';
require_once __DIR__ . '/../../includes/db.php';
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

const TABLE = 'nms_app_settings';
const DEFAULTS = [
  'language'       => 'en-us',
  'defaultWindow'  => 'character',
  'iconSize'       => 'medium',
  'showNegatives'  => true,
  'autoRefreshSec' => 15,
  'theme'          => 'system',
  'recentFirst'    => false,
];

function settings_db(): PDO {
  if (function_exists('db')) return db();
  if (function_exists('nms_db')) return nms_db();
  if (function_exists('get_db')) return get_db();
  global $pdo;
  if ($pdo instanceof PDO) return $pdo;
  throw new RuntimeException('DB');
}

function jexit($d,int $c=200){ http_response_code($c); echo json_encode($d, JSON_UNESCAPED_SLASHES); exit; }

function clean_settings(array $input): array {
  $clean = [];

  if (array_key_exists('language', $input)) {
    $clean['language'] = strtolower(trim((string)$input['language'])) ?: DEFAULTS['language'];
  }

  if (array_key_exists('defaultWindow', $input)) {
    $value = strtolower(trim((string)$input['defaultWindow']));
    $aliases = [
      'vehicles' => 'vehicle',
      'exocraft' => 'vehicle',
      'freighter' => 'frigate',
      'exosuit' => 'character',
      'suit' => 'character',
    ];
    $value = $aliases[$value] ?? $value;
    $allowed = ['character', 'base', 'storage', 'frigate', 'corvette', 'ship', 'vehicle'];
    $clean['defaultWindow'] = in_array($value, $allowed, true) ? $value : DEFAULTS['defaultWindow'];
  }

  if (array_key_exists('iconSize', $input)) {
    $value = strtolower(trim((string)$input['iconSize']));
    $clean['iconSize'] = in_array($value, ['small', 'medium', 'large'], true) ? $value : DEFAULTS['iconSize'];
  }

  if (array_key_exists('showNegatives', $input)) {
    $clean['showNegatives'] = filter_var($input['showNegatives'], FILTER_VALIDATE_BOOL, FILTER_NULL_ON_FAILURE) ?? DEFAULTS['showNegatives'];
  }

  if (array_key_exists('autoRefreshSec', $input)) {
    $value = (int)$input['autoRefreshSec'];
    $clean['autoRefreshSec'] = max(0, min(3600, $value));
  }

  if (array_key_exists('theme', $input)) {
    $value = strtolower(trim((string)$input['theme']));
    $clean['theme'] = in_array($value, ['system', 'light', 'dark'], true) ? $value : DEFAULTS['theme'];
  }

  if (array_key_exists('recentFirst', $input)) {
    $clean['recentFirst'] = filter_var($input['recentFirst'], FILTER_VALIDATE_BOOL, FILTER_NULL_ON_FAILURE) ?? DEFAULTS['recentFirst'];
  }

  return $clean;
}

try {
  $pdo = settings_db(); $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
  try {
    $pdo->exec("CREATE TABLE IF NOT EXISTS `".TABLE."` (
      `id` TINYINT UNSIGNED NOT NULL PRIMARY KEY,
      `settings_json` LONGTEXT NOT NULL,
      `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci");

    $hasSettingsJson = $pdo->query("SHOW COLUMNS FROM `".TABLE."` LIKE 'settings_json'")->fetch(PDO::FETCH_ASSOC);
    if (!$hasSettingsJson) {
      $pdo->exec("ALTER TABLE `".TABLE."` ADD COLUMN `settings_json` LONGTEXT NOT NULL");
    }

    $hasUpdatedAt = $pdo->query("SHOW COLUMNS FROM `".TABLE."` LIKE 'updated_at'")->fetch(PDO::FETCH_ASSOC);
    if (!$hasUpdatedAt) {
      $pdo->exec("ALTER TABLE `".TABLE."` ADD COLUMN `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP");
    }

    $pdo->exec("INSERT IGNORE INTO `".TABLE."` (`id`,`settings_json`) VALUES (1,'{}')");
  } catch (Throwable $e) {
    jexit(['ok'=>false,'error'=>'Settings table initialization failed','detail'=>$e->getMessage()], 500);
  }

  $method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
  if ($method === 'GET') {
    $row = $pdo->query("SELECT settings_json FROM `".TABLE."` WHERE id=1")->fetch(PDO::FETCH_ASSOC);
    $cur = [];
    if ($row && !empty($row['settings_json'])) { $dec = json_decode($row['settings_json'], true); if (is_array($dec)) $cur = $dec; }
    jexit(['ok'=>true,'settings'=>array_replace(DEFAULTS,$cur)]);
  }

  if ($method === 'POST') {
    $in = json_decode(file_get_contents('php://input') ?: '{}', true);
    if (!is_array($in)) jexit(['ok'=>false,'error'=>'Invalid JSON body'], 400);
    $clean = clean_settings($in);

    $row = $pdo->query("SELECT settings_json FROM `".TABLE."` WHERE id=1")->fetch(PDO::FETCH_ASSOC);
    $cur = [];
    if ($row && !empty($row['settings_json'])) { $dec = json_decode($row['settings_json'], true); if (is_array($dec)) $cur=$dec; }
    $merged = array_replace(DEFAULTS,$cur,$clean);
    $stmt = $pdo->prepare("INSERT INTO `".TABLE."` (`id`,`settings_json`) VALUES (1,:j)
                           ON DUPLICATE KEY UPDATE `settings_json`=VALUES(`settings_json`)");
    $stmt->execute([':j'=>json_encode($merged, JSON_UNESCAPED_UNICODE)]);
    jexit(['ok'=>true,'settings'=>$merged]);
  }

  jexit(['ok'=>false,'error'=>'Method not allowed'], 405);
} catch (Throwable $e) {
  jexit(['ok'=>false,'error'=>'Internal error','detail'=>$e->getMessage()], 500);
}
