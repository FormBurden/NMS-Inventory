#!/usr/bin/env php
<?php
declare(strict_types=1);

/**
 * Build public/data/items_local.json from AssistantApps.NoMansSky.Info NuGet bundle.
 *
 * Looks in: .cache/aa/pkg/contentFiles/any/any/Assets/{json,en,*,data}
 *
 * - Pulls English names from Assets/json/en/*.lang.json by keys like UI_<ID>_NAME
 * - Crawls Assets/data/*.json for objects with an ID-ish field (id/ID/enum/etc.)
 * - Infers "kind" from the source filename (Products → product, RawMaterials → substance, etc.)
 * - Merges everything into: { "<ID>": { id, name, kind, icon|null, src } }
 *
 * Usage:
 *   php scripts/build_items_local.php
 *   php scripts/build_items_local.php .cache/aa/pkg public/data/items_local.json
 */

$pkgRoot = $argv[1] ?? '.cache/aa/pkg';
$outFile = $argv[2] ?? 'public/data/items_local.json';

$assetsRoot = findAssetsRoot($pkgRoot);
if (!$assetsRoot) {
    fwrite(STDERR, "ERROR: Could not locate Assets under $pkgRoot\n");
    exit(1);
}
fwrite(STDOUT, "Using Assets root: $assetsRoot\n");
@mkdir(dirname($outFile), 0777, true);

$items = [];   // id => [id,name,kind,icon,src]
$seen  = [];

/* ---------------------------------------------------------------------------
 * 1) English names from language packs: Assets/json/en/*.lang.json
 *    Keys often look like UI_<ID>_NAME → "Starship Launch Fuel"
 * ------------------------------------------------------------------------- */
$langDir = $assetsRoot . '/json/en';
if (is_dir($langDir)) {
    $iter = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($langDir));
    foreach ($iter as $f) {
        if (!$f->isFile()) continue;
        $fn = $f->getFilename();
        if (!str_ends_with(strtolower($fn), '.json')) continue;

        // classify kind by filename
        $kindHint = kindFromLangFilename($fn);

        $map = json_decode(file_get_contents($f->getPathname()), true);
        if (!is_array($map)) continue;

        foreach ($map as $k => $v) {
            if (!is_string($k) || !is_string($v) || $v === '') continue;

            // Match UI_<ID>_NAME (strict) or UI_<ID> (fallback)
            if (preg_match('/^UI_([A-Z0-9^._-]+)_NAME$/', $k, $m) || preg_match('/^UI_([A-Z0-9^._-]+)$/', $k, $m)) {
                $id = strtoupper($m[1]);
                addOrMergeItem($items, $id, [
                    'id'   => $id,
                    'name' => $v,
                    'kind' => $kindHint,
                    'icon' => null,
                    'src'  => $fn,
                ]);
                $seen[$id] = true;
            }
        }
    }
}

/* ---------------------------------------------------------------------------
 * 2) Crawl data JSONs for embedded objects with ID-ish fields
 *    Path: Assets/data/*.json (Recharge.json, catalogue.json, etc.)
 * ------------------------------------------------------------------------- */
$dataDir = $assetsRoot . '/data';
if (is_dir($dataDir)) {
    $iter = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($dataDir));
    foreach ($iter as $f) {
        if (!$f->isFile()) continue;
        $fn = $f->getFilename();
        if (!str_ends_with(strtolower($fn), '.json')) continue;

        $payload = json_decode(file_get_contents($f->getPathname()), true);
        if ($payload === null) continue;

        // Recursively visit every associative array and try to extract an item
        gatherItemsFromNode($payload, $fn, $items);
    }
}

/* ---------------------------------------------------------------------------
 * 3) Finalize & write
 * ------------------------------------------------------------------------- */
ksort($items, SORT_STRING | SORT_FLAG_CASE);
file_put_contents($outFile, json_encode($items, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE));
fwrite(STDOUT, "Wrote " . count($items) . " items to $outFile\n");
exit(0);

/* ============================== helpers ================================== */

function findAssetsRoot(string $root): ?string {
    // Prefer NuGet layout: contentFiles/any/any/Assets
    $preferred = rtrim($root, '/').'/contentFiles/any/any/Assets';
    if (is_dir($preferred)) return realpath($preferred) ?: $preferred;

    // Fallback: direct Assets under pkg root
    $alt = rtrim($root, '/').'/Assets';
    if (is_dir($alt)) return realpath($alt) ?: $alt;

    // Last resort: search anywhere under $root
    $it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($root));
    foreach ($it as $f) {
        if ($f->isDir() && strtolower($f->getFilename()) === 'assets') {
            return $f->getPathname();
        }
    }
    return null;
}

function addOrMergeItem(array &$items, string $id, array $new): void {
    if (!isset($items[$id])) { $items[$id] = $new; return; }
    $cur = $items[$id];

    // Prefer nicer name (longer / contains spaces)
    if ($new['name'] && ($cur['name'] === $id || strlen($new['name']) > strlen($cur['name']))) {
        $cur['name'] = $new['name'];
    }
    // Prefer known kind over null
    if (!$cur['kind'] && $new['kind']) $cur['kind'] = $new['kind'];
    // Prefer icon if provided
    if (!$cur['icon'] && $new['icon']) $cur['icon'] = $new['icon'];

    // Keep provenance of first source file (debug)
    $items[$id] = $cur;
}

function kindFromLangFilename(string $fn): ?string {
    $s = strtolower($fn);
    return match (true) {
        str_contains($s, 'rawmaterials')     => 'substance',
        str_contains($s, 'products')         => 'product',
        str_contains($s, 'tradeitems')       => 'product',
        str_contains($s, 'curiosity')        => 'product',
        str_contains($s, 'others')           => 'product',
        str_contains($s, 'technologymodule') => 'technology',
        str_contains($s, 'technology')       => 'technology',
        str_contains($s, 'proceduralproducts'),
        str_contains($s, 'upgrademodules')   => 'procedural_technology',
        default                              => null,
    };
}

function gatherItemsFromNode(mixed $node, string $srcFile, array &$items): void {
    if (is_array($node)) {
        // If this array looks like an item object, try to extract now
        if (looksLikeItemRow($node)) {
            $id = getIdFromRow($node);
            if ($id) {
                $name = getNameFromRow($node) ?? $id;
                $kind = getKindFromRow($node) ?? kindFromDataFilename($srcFile);
                $icon = getIconFromRow($node);

                addOrMergeItem($items, $id, [
                    'id'   => $id,
                    'name' => $name,
                    'kind' => $kind,
                    'icon' => $icon,
                    'src'  => $srcFile,
                ]);
                // do not return; keep scanning for nested items too
            }
        }
        // Recurse
        foreach ($node as $v) gatherItemsFromNode($v, $srcFile, $items);
    }
    // scalars: ignore
}

function looksLikeItemRow(array $row): bool {
    // Needs an ID-ish field
    $id = getIdFromRow($row);
    if (!$id) return false;

    // Avoid obvious non-items: controller mappings, etc., by checking ID shape
    return (bool)preg_match('/^[A-Z0-9^._-]{3,}$/', $id);
}

function getIdFromRow(array $row): ?string {
    foreach (['id','ID','Id','symbol','key','enum','value','valueEnum'] as $k) {
        if (isset($row[$k]) && is_string($row[$k])) {
            $v = strtoupper(trim($row[$k]));
            if ($v !== '') return $v;
        }
    }
    return null;
}

function getNameFromRow(array $row): ?string {
    foreach (['name','Name','label','Label','title','Title','displayName','DisplayName'] as $k) {
        if (isset($row[$k]) && is_string($row[$k]) && trim($row[$k])!=='') return $row[$k];
    }
    // nested { name: { English: "…" } }
    foreach ($row as $v) {
        if (is_array($v) && isset($v['English']) && is_string($v['English']) && $v['English']!=='') {
            return $v['English'];
        }
    }
    return null;
}

function getKindFromRow(array $row): ?string {
    foreach (['type','Type','category','Category','group','Group','class','Class'] as $k) {
        if (isset($row[$k]) && is_string($row[$k]) && trim($row[$k])!=='') {
            return strtolower($row[$k]);
        }
    }
    return null;
}

function getIconFromRow(array $row): ?string {
    foreach (['icon','Icon','iconPath','iconFilename','IconFilename','texture','Texture','image','Image','wikiIcon','iconName'] as $k) {
        if (isset($row[$k]) && is_string($row[$k]) && trim($row[$k])!=='') return $row[$k];
    }
    return null;
}

function kindFromDataFilename(string $fn): ?string {
    $s = strtolower($fn);
    return match (true) {
        str_contains($s, 'product')      => 'product',
        str_contains($s, 'rawmaterial')  => 'substance',
        str_contains($s, 'substance')    => 'substance',
        str_contains($s, 'technology')   => 'technology',
        str_contains($s, 'procedural')   => 'procedural_technology',
        str_contains($s, 'consumable')   => 'consumable',
        default                          => null,
    };
}
