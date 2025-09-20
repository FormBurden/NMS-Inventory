<?php
declare(strict_types=1);

/**
 * Build items_local.json from Lo2k's "NMS Extracted Tables" Google Sheet and
 * map icon filenames to the NMSCD Enhanced Images repo.
 *
 * Output: public/data/items_local.json
 *
 * Requires: PHP 7.4+ with allow_url_fopen OR curl available
 */

const SHEET_ID = '1J8WdrubKgo8A9hPY-hbQLq4eVrb3n3lZAgiI2J7ncAU';
const OUT_PATH = __DIR__ . '/../public/data/items_local.json';

/** Which tabs to ingest (sheet tab names must match the Google Sheet exactly) */
$SHEETS = [
  'SUBSTANCES' => 'substance',
  'PRODUCTS'   => 'product',
  'TECHNOLOGY' => 'technology',
  'CONSUMABLES'=> 'consumable',
  'PROC. TECH' => 'procedural_tech', // includes upgrade modules
];

/** Fetch a Google Sheet tab as CSV via the gviz “out:csv” endpoint */
function fetch_csv(string $sheetTab): array {
  $url = sprintf(
    'https://docs.google.com/spreadsheets/d/%s/gviz/tq?tqx=out:csv&sheet=%s',
    SHEET_ID,
    rawurlencode($sheetTab)
  );
  $csv = http_get($url);
  if ($csv === null) throw new RuntimeException("Failed to fetch CSV for tab: $sheetTab");
  $rows = array_map('str_getcsv', preg_split("/\r\n|\n|\r/", trim($csv)));
  if (!$rows) return [];
  // header -> index map (case/space insensitive)
  $header = array_map(fn($h)=> strtolower(preg_replace('/\s+/', '', $h)), $rows[0]);
  $idx = fn($name, $alts=[]) => (function($header, $wanted, $alts){
      foreach (array_merge([$wanted], $alts) as $w) {
        $k = strtolower(preg_replace('/\s+/', '', $w));
        $i = array_search($k, $header, true);
        if ($i !== false) return $i;
      }
      return -1;
  })($header, $name, $alts);

  $idI   = $idx('ID');
  $nameI = $idx('Name',['NameUpper','NameKey']);
  $nameLowerI = $idx('NameLower',['LowerName','NameLowerKey']);
  $iconI = $idx('Filename',['Icon','IconFilename','Icon File','IconPath']);
  $subI  = $idx('Subtitle',['SubTitle','SubtitleValue','Sub']);
  $descI = $idx('Description',['Desc','DescriptionValue']);

  $out = [];
  for ($r=1; $r<count($rows); $r++) {
    $row = $rows[$r];
    if (!isset($row[$idI])) continue;
    $gameId = trim((string)$row[$idI]);
    if ($gameId === '' || $gameId === 'ID') continue;

    $iconPath = $iconI>=0 && isset($row[$iconI]) ? trim((string)$row[$iconI]) : '';
    $iconUrl  = icon_from_dds($iconPath);

    $nameKey = $nameI>=0 && isset($row[$nameI]) ? trim((string)$row[$nameI]) : '';
    $nameLowerKey = $nameLowerI>=0 && isset($row[$nameLowerI]) ? trim((string)$row[$nameLowerI]) : '';

    $out[] = [
      'gameId'     => $gameId,
      'nameKey'    => $nameKey,
      'nameLowerKey'=> $nameLowerKey,
      'subtitleKey'=> $subI>=0 && isset($row[$subI]) ? trim((string)$row[$subI]) : '',
      'descKey'    => $descI>=0 && isset($row[$descI]) ? trim((string)$row[$descI]) : '',
      'icon'       => $iconUrl,
      // Keep the raw DDS so you can retarget later if you want
      'iconDDS'    => $iconPath,
    ];
  }
  return $out;
}

/** Build a strings map (key => English text) from the “Strings” tab */
function fetch_strings(): array {
  $url = sprintf(
    'https://docs.google.com/spreadsheets/d/%s/gviz/tq?tqx=out:csv&sheet=%s',
    SHEET_ID,
    rawurlencode('Strings')
  );
  $csv = http_get($url);
  if ($csv === null) return [];
  $rows = array_map('str_getcsv', preg_split("/\r\n|\n|\r/", trim($csv)));
  if (!$rows) return [];
  $header = array_map(fn($h)=> strtolower(preg_replace('/\s+/', '', $h)), $rows[0]);
  $keyI = array_search('id', $header, true);
  if ($keyI === false) $keyI = 0;
  // prefer the column that looks most like English
  $engI = null;
  foreach (['english','en','usenglish','text'] as $want) {
    $i = array_search($want, $header, true);
    if ($i !== false) { $engI = $i; break; }
  }
  if ($engI === null) $engI = 1;
  $map = [];
  for ($i=1; $i<count($rows); $i++) {
    $k = trim((string)$rows[$i][$keyI] ?? '');
    $v = trim((string)$rows[$i][$engI] ?? '');
    if ($k !== '') $map[$k] = $v;
  }
  return $map;
}

/** Convert game DDS path to a stable PNG URL in the Enhanced Images repo */
function icon_from_dds(string $dds): string {
  if ($dds === '') return '';
  // Grab base filename without extension: e.g. SUBSTANCE.FUEL.1.DDS -> SUBSTANCE.FUEL.1
  $base = pathinfo($dds, PATHINFO_FILENAME);
  $upper = strtoupper($base);

  // Guess category from base name
  $folder = 'Misc';
  if (str_starts_with($upper, 'SUBSTANCE.'))   $folder = 'Substances';
  elseif (str_starts_with($upper, 'PRODUCT.')) $folder = 'Products';
  elseif (str_starts_with($upper, 'TECHNOLOGY.')) $folder = 'Technology';
  elseif (str_starts_with($upper, 'U3') || str_starts_with($upper, 'U4') || str_starts_with($upper, 'U5')) {
    // some tech icons have different prefixes; fall back to Technology
    $folder = 'Technology';
  }

  // Repo path (optimized versions kept under AssistantNMS folder)
  return sprintf(
    'https://raw.githubusercontent.com/NMSCD/No-Mans-Sky-Enhanced-Images/master/AssistantNMS/%s/%s.png',
    $folder,
    $base
  );
}

/** HTTP get via file_get_contents or curl */
function http_get(string $url): ?string {
  // try fopen
  $ctx = stream_context_create(['http'=>['timeout'=>30], 'ssl'=>['verify_peer'=>true, 'verify_peer_name'=>true]]);
  $data = @file_get_contents($url, false, $ctx);
  if ($data !== false) return $data;

  // try curl
  if (function_exists('curl_init')) {
    $ch = curl_init($url);
    curl_setopt_array($ch, [
      CURLOPT_RETURNTRANSFER => true,
      CURLOPT_FOLLOWLOCATION => true,
      CURLOPT_TIMEOUT => 30,
      CURLOPT_SSL_VERIFYPEER => true,
      CURLOPT_SSL_VERIFYHOST => 2,
      CURLOPT_USERAGENT => 'NMS-Inventory-Script/1.0'
    ]);
    $data = curl_exec($ch);
    curl_close($ch);
    if ($data !== false) return $data;
  }
  return null;
}

/** Compose final items map: gameId => { name, type, ... } */
function build_items(array $sheets, array $strings): array {
  $items = [];
  foreach ($sheets as $tab => $type) {
    $rows = fetch_csv($tab);
    foreach ($rows as $row) {
      $gid = $row['gameId'];
      // prefer readable names if present in strings
      $name = '';
      foreach (['nameKey','nameLowerKey'] as $k) {
        $key = $row[$k] ?? '';
        if ($key && isset($strings[$key])) { $name = $strings[$key]; break; }
      }
      if ($name === '') $name = $row['nameKey'] ?: $row['nameLowerKey'] ?: $gid;

      $subtitle = ($row['subtitleKey'] && isset($strings[$row['subtitleKey']])) ? $strings[$row['subtitleKey']] : '';
      $desc     = ($row['descKey'] && isset($strings[$row['descKey']])) ? $strings[$row['descKey']] : '';

      $items[$gid] = [
        'id'       => $gid,
        'type'     => $type,
        'name'     => $name,
        'subtitle' => $subtitle,
        'desc'     => $desc,
        'icon'     => $row['icon'],
        'iconDDS'  => $row['iconDDS'],
      ];
    }
  }
  ksort($items);
  return $items;
}

/** --- run --- */
try {
  $strings = fetch_strings();
  $items = build_items($SHEETS, $strings);

  // Ensure path exists
  @mkdir(dirname(OUT_PATH), 0775, true);
  file_put_contents(OUT_PATH, json_encode($items, JSON_PRETTY_PRINT|JSON_UNESCAPED_SLASHES));
  echo "Wrote " . count($items) . " items to " . OUT_PATH . PHP_EOL;
  exit(0);
} catch (Throwable $e) {
  fwrite(STDERR, "ERROR: " . $e->getMessage() . PHP_EOL);
  exit(1);
}
