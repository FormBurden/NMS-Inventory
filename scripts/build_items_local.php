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

$aliasCount = applyCatalogueAliases($items);

ksort($items, SORT_STRING | SORT_FLAG_CASE);
@mkdir(dirname($outFile), 0777, true);
file_put_contents($outFile, json_encode($items, JSON_PRETTY_PRINT|JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE));
echo "Wrote " . count($items) . " items (with english names: $withName, aliases: $aliasCount) to $outFile\n";

/* ========================== helpers =========================== */

function fail(string $msg): void { fwrite(STDERR, "ERROR: $msg\n"); exit(1); }

function findAssetsRoot(string $pkgRoot): ?string {
    $root = rtrim($pkgRoot, '/');

    // Prefer NuGet layout
    $preferred = $root . '/contentFiles/any/any/Assets';
    if (is_dir($preferred)) return realpath($preferred) ?: $preferred;

    // Fallback: plain Assets
    $alt = $root . '/Assets';
    if (is_dir($alt)) return realpath($alt) ?: $alt;

    // Last-resort recursive lookup for package layout changes
    if (!is_dir($root)) return null;

    $d = new RecursiveDirectoryIterator($root, FilesystemIterator::SKIP_DOTS);
    $it = new RecursiveIteratorIterator($d, RecursiveIteratorIterator::SELF_FIRST);
    foreach ($it as $f) {
        if (!$f->isDir()) continue;
        if ($f->getFilename() !== 'Assets') continue;

        $candidate = $f->getPathname();
        if (is_dir($candidate . '/data') && is_dir($candidate . '/json')) {
            return realpath($candidate) ?: $candidate;
        }
    }

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

function applyCatalogueAliases(array &$items): int {
    $added = 0;

    foreach (array_keys($items) as $id) {
        if (str_starts_with($id, 'BOBBLE_') || str_starts_with($id, 'SHIP_')) {
            $added += addItemAlias($items, 'T_' . $id, $id);
        }
    }

    $exactAliases = [
        'U_BOLT1' => 'BOLT',
        'U_BOLT4' => 'BOLT',
        'U_BOLTX' => 'UT_BOLT',
        'U_RAD2' => 'UT_RAD',
        'U_RAD3' => 'UT_RAD',
        'U_RAIL4' => 'UT_RAIL',
        'U_SHIPGUN1' => 'SHIPGUN1',
    ];

    foreach ($exactAliases as $alias => $target) {
        $added += addItemAlias($items, $alias, $target);
    }

    $upgradeFamilies = [
        'UP_BOLT' => 'UT_BOLT',
        'UP_COLD' => 'UT_COLD',
        'UP_HOT' => 'UT_HOT',
        'UP_JET' => 'UT_JET',
        'UP_LASER' => 'LASER',
        'UP_RAD' => 'UT_RAD',
        'UP_RAIL' => 'UT_RAIL',
        'UP_SCAN' => 'UT_SCAN',
        'UP_SHOT' => 'UT_SHOT',
        'UP_SMG' => 'UT_SMG',
        'UP_TOX' => 'UT_TOX',
        'UP_S_SHL' => 'UT_SHIPSHIELD',
    ];

    foreach ($upgradeFamilies as $prefix => $target) {
        $added += addTieredAliases($items, $prefix, $target);
    }

    $added += addTieredAliases($items, 'UP_SHLD', 'PROTECT', 'Shield Module');

    $proceduralUpgradeFamilies = [
        'UP_HYP' => [['UT_HYP', 'HYPERDRIVE'], 'Hyperdrive Module'],
        'UP_HAZ' => [['UT_HAZ', 'PROTECT'], 'Hazard Protection Module'],
        'UP_PULSE' => [['UT_PULSE', 'SHIPJUMP1'], 'Pulse Engine Module'],
        'UP_GREN' => [['UT_GREN', 'GRENADE'], 'Plasma Launcher Module'],
        'UP_MCGUN' => [['UT_MCGUN', 'SHIPMINIGUN', 'SHIPGUN1'], 'Infra-Knife Accelerator Module'],
        'UP_SBLOB' => [['UT_SBLOB', 'SHIPBLOB', 'SHIPGUN1'], 'Cyclotron Ballista Module'],
        'UP_SGUN' => [['UT_SGUN', 'SHIPGUN1'], 'Photon Cannon Module'],
        'UP_EXLAS' => [['UT_EXLAS', 'EXOCRAFTLASER', 'LASER'], 'Exocraft Mining Laser Module'],
        'UP_MCENG' => [['UT_MCENG', 'VEHICLE_ENGINE'], 'Exocraft Engine Module'],
        'UP_SLASR' => [['UT_SLASR', 'SHIPLAS1'], 'Phase Beam Module'],
        'UP_SSHOT' => [['UT_SSHOT', 'SHIPSHOTGUN'], 'Positron Ejector Module'],
        'UP_UNW' => [['UT_UNW', 'WATERPROT'], 'Underwater Protection Module'],
    ];

    foreach ($proceduralUpgradeFamilies as $prefix => $targetAndName) {
        $added += addTieredAliasesFromCandidates($items, $prefix, $targetAndName[0], $targetAndName[1]);
    }

    $proceduralExactAliases = [
        'U_PULSE2' => [['SHIPJUMP1', 'UT_PULSE'], 'Pulse Engine'],
        'U_HYPERX' => [['HYPERDRIVE', 'UT_HYP'], 'Hyperdrive'],
        'U_PULSEX' => [['SHIPJUMP1', 'UT_PULSE'], 'Pulse Engine'],
        'U_GRENADEX' => [['GRENADE', 'UT_GREN'], 'Plasma Launcher'],
        'U_COLDPROT2' => [['UT_COLD', 'COLDPROT'], 'Thermal Protection'],
        'U_HOTPROT2' => [['UT_HOT', 'HOTPROT'], 'Thermal Protection'],
        'U_UNW2' => [['WATERPROT', 'UT_UNW'], 'Underwater Protection'],
    ];

    foreach ($proceduralExactAliases as $alias => $targetAndName) {
        $added += addItemAliasFromCandidates($items, $alias, $targetAndName[0], $targetAndName[1], 'Technology');
    }

    $corvetteFamilies = [
        'CV_LAUN' => ['LAUNCHER', 'Corvette Launch Thruster Module'],
        'CV_PULSE' => ['SHIPJUMP1', 'Corvette Pulse Engine Module'],
        'CV_S_SHL' => ['SHIPSHIELD', 'Corvette Deflector Shield Module'],
        'CV_HYP' => ['HYPERDRIVE', 'Corvette Hyperdrive Module'],
        'CV_SGUN' => ['SHIPGUN1', 'Corvette Photon Cannon Module'],
        'CV_SLASR' => ['SHIPLAS1', 'Corvette Phase Beam Module'],
        'CV_SROC' => ['SHIPROCKETS', 'Corvette Rocket Launcher Module'],
        'CV_SSHOT' => ['SHIPSHOTGUN', 'Corvette Positron Ejector Module'],
    ];

    foreach ($corvetteFamilies as $prefix => $targetAndName) {
        $added += addTieredAliases($items, $prefix, $targetAndName[0], $targetAndName[1]);
    }

    $added += addSyntheticItem($items, 'CV_INV1', 'Corvette Inventory Module', 'Technology');
    $added += addSyntheticItem($items, 'CV_INV2', 'Corvette Inventory Module', 'Technology');
    $added += addSyntheticItem($items, 'CV_FIT1', 'Corvette Fitting Module', 'Technology');
    $added += addSyntheticItem($items, 'CV_FIT3', 'Corvette Fitting Module', 'Technology');
    $added += addSyntheticItem($items, 'CV_SCI3', 'Corvette Scanner Module', 'Technology');

    $added += addSyntheticItem($items, 'PROC_HIST', 'Procedural History Item', 'Product');
    $added += addSyntheticItem($items, 'PROC_TOOL', 'Procedural Multi-Tool Item', 'Product');
    $added += addSyntheticItem($items, 'SHIP_CORE_C', 'Starship Core Component', 'Product');

    $added += applyBuildingCatalogueSeeds($items);

    return $added;
}

function addTieredAliases(array &$items, string $prefix, string $target, ?string $name = null): int {
    $added = 0;
    foreach (['1', '2', '3', '4', 'X'] as $tier) {
        $added += addItemAlias($items, $prefix . $tier, $target, $name);
    }
    return $added;
}

function addTieredAliasesFromCandidates(array &$items, string $prefix, array $targets, string $name, string $kind = 'Technology'): int {
    $added = 0;
    foreach (['1', '2', '3', '4', 'X'] as $tier) {
        $added += addItemAliasFromCandidates($items, $prefix . $tier, $targets, $name, $kind);
    }
    return $added;
}

function addItemAliasFromCandidates(array &$items, string $alias, array $targets, string $name, string $kind = 'Technology'): int {
    foreach ($targets as $target) {
        $target = strtoupper(trim((string)$target));
        if ($target !== '' && isset($items[$target]) && is_array($items[$target])) {
            return addItemAlias($items, $alias, $target, $name);
        }
    }

    return addSyntheticItem($items, $alias, $name, $kind);
}

function addItemAlias(array &$items, string $alias, string $target, ?string $name = null): int {
    $alias = strtoupper(trim($alias));
    $target = strtoupper(trim($target));

    if ($alias === '' || $target === '' || isset($items[$alias]) || !isset($items[$target]) || !is_array($items[$target])) {
        return 0;
    }

    $row = $items[$target];
    $row['id'] = $alias;
    $row['aliasOf'] = $target;

    if ($name !== null && $name !== '') {
        $row['name'] = $name;
    }

    $items[$alias] = $row;
    return 1;
}

function addSyntheticItem(array &$items, string $id, string $name, string $kind): int {
    $id = strtoupper(trim($id));

    if ($id === '' || isset($items[$id])) {
        return 0;
    }

    $items[$id] = [
        'id' => $id,
        'name' => $name,
        'kind' => $kind,
        'icon' => null,
        'appId' => null,
        'synthetic' => true,
    ];

    return 1;
}

function applyBuildingCatalogueSeeds(array &$items): int {
    $path = __DIR__ . '/../data/mappings/building_catalogue_seeds.json';

    if (!is_file($path)) {
        return 0;
    }

    $rows = json_decode(file_get_contents($path), true);
    if (!is_array($rows)) {
        fwrite(STDERR, "WARNING: Invalid JSON: $path\n");
        return 0;
    }

    $added = 0;
    foreach ($rows as $row) {
        if (!is_array($row)) {
            continue;
        }

        $id = strtoupper(trim((string)($row['id'] ?? '')));
        $name = trim((string)($row['name'] ?? ''));
        $kind = trim((string)($row['kind'] ?? 'Building'));
        $appIds = $row['appIds'] ?? [];

        if ($id === '' || $name === '') {
            continue;
        }

        if (!is_array($appIds)) {
            $appIds = [];
        }

        $added += addCatalogueSeedFromCandidates($items, $id, $appIds, $name, $kind ?: 'Building');
    }

    return $added;
}

function addCatalogueSeedFromCandidates(array &$items, string $alias, array $appIds, string $name, string $kind): int {
    $alias = strtoupper(trim($alias));

    if ($alias === '' || isset($items[$alias])) {
        return 0;
    }

    foreach ($items as $row) {
        if (!is_array($row)) {
            continue;
        }

        $appId = $row['appId'] ?? null;
        if (!is_string($appId) || !in_array($appId, $appIds, true)) {
            continue;
        }

        $items[$alias] = [
            'id' => $alias,
            'name' => $name,
            'kind' => $kind,
            'icon' => $row['icon'] ?? null,
            'appId' => $appId,
            'aliasOf' => $row['id'] ?? null,
        ];

        return 1;
    }

    return addSyntheticItem($items, $alias, $name, $kind);
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
