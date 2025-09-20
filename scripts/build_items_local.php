#!/usr/bin/env php
<?php
declare(strict_types=1);

/**
 * Build public/data/items_local.json by joining:
 *  - Assets/data/developerDetails.json  (App Id -> GameId, Icon DDS, etc.)
 *  - Assets/json/en-us/*.lang.json      (en-US item arrays: Id, Name, Icon, CdnUrl, …)
 *
 * Output schema: { "<GameId>": { id, name, kind, icon, appId } }
 *
 * Usage:
 *   php scripts/build_items_local.php
 *   php scripts/build_items_local.php .cache/aa/pkg public/data/items_local.json
 */

$pkgRoot = $argv[1] ?? '.cache/aa/pkg';
$outFile = $argv[2] ?? 'public/data/items_local.json';

$assetsRoot = findAssetsRoot($pkgRoot);
if (!$assetsRoot) fail("Could not locate Assets under $pkgRoot");

$enDir   = findLangDir($assetsRoot);      // prefer json/en-us
$dataDir = $assetsRoot . '/data';
if (!is_dir($dataDir)) fail("Missing Assets/data under $assetsRoot");

echo "Using Assets root: $assetsRoot\n";
echo "Using en-us dir:   " . ($enDir ?: '<none>') . "\n";

/* 1) Build en-us item map: app Id -> {name, icon (cdn), kind} */
$enMap = $enDir ? buildEnUsMap($enDir) : [];
echo "en-us items indexed: " . count($enMap) . "\n";

/* 2) Read developerDetails (App Id -> GameId, Icon DDS, …) */
$devPath = $dataDir . '/developerDetails.json';
if (!is_file($devPath)) fail("Missing $devPath");
$devRows = json_decode(file_get_contents($devPath), true);
if (!is_array($devRows)) fail("Invalid JSON: $devPath");

$items = [];
$withName = 0;
foreach ($devRows as $row) {
    $appId = $row['Id'] ?? null;
    if (!is_string($appId) || $appId === '') continue;

    // Pull the flat Properties dict
    $props = [];
    foreach ((array)($row['Properties'] ?? []) as $p) {
        if (isset($p['Name'], $p['Value'])) $props[$p['Name']] = $p['Value'];
    }
    $gameId = strtoupper(trim((string)($props['GameId'] ?? '')));
    if ($gameId === '') continue;

    // Prefer en-us name/icon/kind from enMap[appId]
    $en = $enMap[$appId] ?? null;
    $name = $en['name'] ?? null;
    $kind = $en['kind'] ?? null;
    $icon = $en['icon'] ?? null;

    // If no PNG icon in enMap, derive from DDS path (developerDetails.Icon)
    if (!$icon && !empty($props['Icon']) && is_string($props['Icon'])) {
        $base = pathinfo($props['Icon'], PATHINFO_FILENAME); // e.g. SUBSTANCE.FUEL.1
        $icon = "https://nomanssky.fandom.com/wiki/Special:FilePath/{$base}.png";
        if (!$kind) {
            if (str_starts_with_ci($base, 'SUBSTANCE.'))   $kind = 'Substance';
            elseif (str_starts_with_ci($base, 'PRODUCT.')) $kind = 'Product';
            elseif (str_starts_with_ci($base, 'TECHNOLOGY.')) $kind = 'Technology';
        }
    }

    // Final fallbacks
    if (!$name) $name = $gameId;
    if (!$kind) $kind = null;

    $items[$gameId] = [
        'id'    => $gameId,
        'name'  => $name,
        'kind'  => $kind,
        'icon'  => $icon,       // may be null (UI will fall back to /api/icon.php)
        'appId' => $appId,
    ];
    if ($name && $name !== $gameId) $withName++;
}

ksort($items, SORT_STRING | SORT_FLAG_CASE);
@mkdir(dirname($outFile), 0777, true);
file_put_contents($outFile, json_encode($items, JSON_PRETTY_PRINT|JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE));
echo "Wrote " . count($items) . " items (with english names: $withName) to $outFile\n";

/* ========================== helpers =========================== */

function fail(string $msg): void { fwrite(STDERR, "ERROR: $msg\n"); exit(1); }

function findAssetsRoot(string $pkgRoot): ?string {
    // Prefer NuGet layout
    $preferred = rtrim($pkgRoot, '/').'/contentFiles/any/any/Assets';
    if (is_dir($preferred)) return realpath($preferred) ?: $preferred;
    // Fallback: plain Assets
    $alt = rtrim($pkgRoot, '/').'/Assets';
    if (is_dir($alt)) return realpath($alt) ?: $alt;
    return null;
}

function findLangDir(string $assetsRoot): ?string {
    // Prefer json/en-us
    $enUS = $assetsRoot . '/json/en-us';
    if (is_dir($enUS)) return realpath($enUS) ?: $enUS;
    // Accept json/en
    $en = $assetsRoot . '/json/en';
    if (is_dir($en)) return realpath($en) ?: $en;
    // Accept a sibling "en-us" (if user manually supplied it)
    $sibling = dirname($assetsRoot) . '/en-us';
    if (is_dir($sibling)) return realpath($sibling) ?: $sibling;
    return null;
}

function buildEnUsMap(string $langDir): array {
    $map = []; // appId => ['name'=>..., 'icon'=>..., 'kind'=>...]
    $d = new RecursiveDirectoryIterator($langDir, FilesystemIterator::SKIP_DOTS);
    $it = new RecursiveIteratorIterator($d);
    foreach ($it as $f) {
        if (!$f->isFile()) continue;
        $fn = $f->getFilename();
        if (!str_ends_with_ci($fn, '.json')) continue;
        $kind = kindFromLangFilename($fn);

        $arr = json_decode(file_get_contents($f->getPathname()), true);
        if (!is_array($arr)) continue;

        foreach ($arr as $row) {
            if (!is_array($row)) continue;
            $appId = $row['Id'] ?? null;
            if (!is_string($appId) || $appId === '') continue;

            $name = null;
            foreach (['Name','Label','Title'] as $k) {
                if (isset($row[$k]) && is_string($row[$k]) && $row[$k] !== '') { $name = $row[$k]; break; }
            }
            // Choose a PNG icon URL if present
            $icon = null;
            if (!empty($row['CdnUrl']) && is_string($row['CdnUrl'])) {
                $icon = $row['CdnUrl'];
            } elseif (!empty($row['Icon']) && is_string($row['Icon'])) {
                // icons are relative like "rawMaterials/9.png"
                $icon = "https://cdn.nmsassistant.com/" . ltrim($row['Icon'], '/');
            }

            // Merge (prefer richer name/icon; keep first non-null kind)
            if (!isset($map[$appId])) $map[$appId] = ['name'=>null,'icon'=>null,'kind'=>null];
            if ($name && ( $map[$appId]['name'] === null || wantsBetterName($map[$appId]['name'], $name) )) $map[$appId]['name'] = $name;
            if ($icon) $map[$appId]['icon'] = $icon;
            if ($kind && !$map[$appId]['kind']) $map[$appId]['kind'] = $kind;
        }
    }
    return $map;
}

function kindFromLangFilename(string $fn): ?string {
    $s = strtolower($fn);
    return match (true) {
        str_starts_with_ci($s, 'rawmaterials')      => 'Substance',
        str_starts_with_ci($s, 'products')          => 'Product',
        str_starts_with_ci($s, 'tradeitems')        => 'Product',
        str_starts_with_ci($s, 'curiosity')         => 'Product',
        str_starts_with_ci($s, 'others')            => 'Product',
        str_starts_with_ci($s, 'cooking')           => 'Product',
        str_starts_with_ci($s, 'technology')        => 'Technology',
        str_starts_with_ci($s, 'constructedtechnology') => 'Technology',
        str_starts_with_ci($s, 'upgrademodules')    => 'Technology',
        str_starts_with_ci($s, 'technologymodule')  => 'Technology',
        str_starts_with_ci($s, 'proceduralproducts')=> 'Product',
        default                                      => null,
    };
}

function wantsBetterName(string $have, string $candidate): bool {
    // Prefer names that aren’t just the GameId, longer/with spaces
    if ($have === strtoupper($have)) return true;
    return strlen($candidate) > strlen($have);
}

/* case-insensitive helpers */
function str_starts_with_ci(string $haystack, string $needle): bool {
    return strncasecmp($haystack, $needle, strlen($needle)) === 0;
}
function str_ends_with_ci(string $haystack, string $needle): bool {
    $len = strlen($needle);
    if ($len === 0) return true;
    return strncasecmp(substr($haystack, -$len), $needle, $len) === 0;
}
