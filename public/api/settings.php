<?php
declare(strict_types=1);

require_once __DIR__ . '/../../includes/db.php';
if (is_file(__DIR__ . '/../../includes/bootstrap.php')) require_once __DIR__ . '/../../includes/bootstrap.php';
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

const TABLE = 'nms_settings';
const DEFAULTS = [
  'language'       => 'en-us',
  'defaultWindow'  => 'Character',
  'iconSize'       => 'medium',
  'showNegatives'  => true,
  'autoRefreshSec' => 15,
  'theme'          => 'system',
  'recentFirst'    => false,
];

function db(): PDO { if (function_exists('get_db')) return get_db(); global $pdo; if ($pdo instanceof PDO) return $pdo; throw new RuntimeException('DB'); }
function jexit($d,int $c=200){ http_response_code($c); echo json_encode($d, JSON_UNESCAPED_SLASHES); exit; }

try {
  $pdo = db(); $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
  try {
    $pdo->exec("CREATE TABLE IF NOT EXISTS `".TABLE."` (
      `id` TINYINT UNSIGNED NOT NULL PRIMARY KEY,
      `settings_json` LONGTEXT NOT NULL,
      `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci");
    $pdo->exec("INSERT IGNORE INTO `".TABLE."` (`id`,`settings_json`) VALUES (1,'{}')");
  } catch (Throwable $e) { /* ignore */ }

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
    $clean = [];
    foreach (array_keys(DEFAULTS) as $k) if (array_key_exists($k,$in)) $clean[$k]=$in[$k];

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
