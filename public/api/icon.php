<?php
declare(strict_types=1);

/**
 * Smart icon resolver, proxy, and persistent cache.
 *
 * How it works:
 * - Checks a persistent disk cache first (public/icons/ID.png -> ../cache/icons/ID.png).
 * - If not cached (or refresh=1), tries:
 *      1) Exact URL in items_local.json (proxied and cached, unless it is the NMS CDN path we rebuild).
 *      2) NMS CDN primary path from that URL if present (proxied and cached).
 *      3) Alternate NMS CDN categories (from .cache/aa/cdn_icon_index.json if available).
 *      4) Fandom fallback candidates from includes/icon_map.php (proxied and cached).
 * - On success, the file is stored in cache and served with long cache headers.
 * - On failure, serves the local placeholder.
 *
 * GET params:
 *   id        = resource id (e.g., OXYGEN or ^AMMO)  [required]
 *   type      = Product | Technology | Substance     [optional hint]
 *   refresh   = 1 to force re-download & overwrite cache for this id
 */

require_once __DIR__ . '/../../includes/icon_map.php';

$PLACEHOLDER = '/assets/img/placeholder.png';
$ITEMS_PATH  = __DIR__ . '/../data/items_local.json';
$CDN_INDEX   = __DIR__ . '/../../.cache/aa/cdn_icon_index.json';
$CDN_BASE    = 'https://cdn.nmsassistant.com';

// public/icons is a symlink to ../cache/icons in your tree; write directly to that backing dir.
$CACHE_DIR   = realpath(__DIR__ . '/../../cache/icons') ?: (__DIR__ . '/../../cache/icons');

// -------- helpers --------
function send_png_headers(int $maxAge = 86400): void {
    header('Content-Type: image/png');
    header('Cache-Control: public, max-age=' . $maxAge);
}

function serve_file_and_exit(string $path, int $maxAge = 604800): void {
    send_png_headers($maxAge);
    readfile($path);
    exit;
}

function serve_placeholder_and_exit(string $ph): void {
    $full = $_SERVER['DOCUMENT_ROOT'] . $ph; // public/assets/img/placeholder.png
    if (is_file($full)) {
        send_png_headers(3600);
        readfile($full);
    } else {
        header('HTTP/1.1 404 Not Found');
    }
    exit;
}

function ensure_dir(string $dir): bool {
    return is_dir($dir) || @mkdir($dir, 0775, true);
}

function cache_path(string $id): string {
    global $CACHE_DIR;
    return rtrim($CACHE_DIR, '/\\') . '/' . $id . '.png';
}

function load_json(string $path): array {
    if (is_file($path)) {
        $j = json_decode(@file_get_contents($path), true);
        if (is_array($j)) return $j;
    }
    return [];
}

function cdn_has(array $idx, string $cat, int $id): bool {
    return isset($idx['categories'][$cat]) && is_array($idx['categories'][$cat])
        ? in_array($id, $idx['categories'][$cat], true)
        : false;
}

function cdn_url(string $cat, int $id): string {
    global $CDN_BASE;
    return rtrim($CDN_BASE, '/') . '/' . rawurlencode($cat) . '/' . $id . '.png';
}

function fallback_categories(string $type): array {
    $t = strtolower($type);
    switch ($t) {
        case 'product':
            return ['products','tradeItems','proceduralProducts','curiosities','rawMaterials','other','cooking'];
        case 'technology':
            return ['technology','constructedTechnology','upgradeModules','building','products'];
        case 'substance':
        case 'rawmaterials':
        case 'substances':
            return ['rawMaterials','products','tradeItems','curiosities'];
        default:
            return ['products','rawMaterials','tradeItems','curiosities','other','technology','constructedTechnology','upgradeModules','building'];
    }
}

/**
 * Download a remote image (preferably PNG) and return the bytes, or null on failure.
 */
function download_png_bytes(string $url, int $timeout = 6): ?string {
    $ch = curl_init($url);
    if (!$ch) return null;
    curl_setopt_array($ch, [
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_MAXREDIRS      => 3,
        CURLOPT_CONNECTTIMEOUT => 4,
        CURLOPT_TIMEOUT        => $timeout,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_USERAGENT      => 'NMS-Inventory/1.0 (+local)',
        CURLOPT_HTTPHEADER     => ['Accept: image/png,image/*;q=0.8,*/*;q=0.5'],
    ]);
    $body = curl_exec($ch);
    $code = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $ctype= (string)curl_getinfo($ch, CURLINFO_CONTENT_TYPE);
    curl_close($ch);

    if ($code >= 200 && $code < 300 && is_string($body) && strlen($body) > 0) {
        // Be lenient: some sources return "image/*" or omit charset; accept any image
        if ($ctype === '' || stripos($ctype, 'image') !== false) {
            return $body;
        }
    }
    return null;
}

/**
 * Save bytes atomically to cache path, then serve the cached file.
 */
function save_and_serve_cache(string $id, string $bytes): bool {
    $dest = cache_path($id);
    if (!ensure_dir(dirname($dest))) return false;

    $tmp  = $dest . '.tmp.' . bin2hex(random_bytes(4));
    if (@file_put_contents($tmp, $bytes) === false) return false;
    @chmod($tmp, 0644);
    // Atomic swap
    if (!@rename($tmp, $dest)) {
        @unlink($tmp);
        return false;
    }
    serve_file_and_exit($dest, 604800);
    return true; // never actually reaches due to exit
}

/**
 * Fetch a URL, write into cache for $id on success, and serve it.
 */
function fetch_cache_and_serve(string $url, string $id): bool {
    $bytes = download_png_bytes($url);
    if ($bytes === null) return false;
    return save_and_serve_cache($id, $bytes);
}

// -------- input --------
$id      = isset($_GET['id']) ? strtoupper(ltrim(urldecode((string)$_GET['id']), '^')) : '';
$type    = isset($_GET['type']) ? (string)$_GET['type'] : '';
$refresh = isset($_GET['refresh']) && $_GET['refresh'] !== '0';

if ($id === '') {
    serve_placeholder_and_exit($PLACEHOLDER);
}

// 0) If not forced refresh, try local override / persistent cache first.
//    Note: public/icons is a symlink to ../cache/icons in your repo layout.
$localSymlinkPath = __DIR__ . '/../icons/' . $id . '.png';
$directCachePath  = cache_path($id);
if (!$refresh) {
    if (is_file($localSymlinkPath)) {
        serve_file_and_exit($localSymlinkPath, 604800);
    }
    if ($directCachePath !== $localSymlinkPath && is_file($directCachePath)) {
        serve_file_and_exit($directCachePath, 604800);
    }
}

// 1) Load item metadata for hints
$items = load_json($ITEMS_PATH);
$entry = is_array($items) ? ($items[$id] ?? null) : null;
if ($entry && !$type) {
    $type = (string)($entry['kind'] ?? $type);
}
$icon   = is_array($entry) ? (string)($entry['icon'] ?? '') : '';
$appId  = is_array($entry) && isset($entry['appId']) && is_numeric($entry['appId']) ? (int)$entry['appId'] : null;

// 2) If metadata has an absolute URL that is NOT the NMS CDN, fetch & cache that.
if ($icon && filter_var($icon, FILTER_VALIDATE_URL)) {
    $host = parse_url($icon, PHP_URL_HOST) ?: '';
    if (strcasecmp($host, 'cdn.nmsassistant.com') !== 0) {
        if (fetch_cache_and_serve($icon, $id)) { /* served */ }
        // If it failed, continue with CDN fallback.
    }
}

// 3) Work out a primary CDN cat/id if the icon already points to cdn
$primaryCat = '';
$primaryId  = null;
if ($icon && filter_var($icon, FILTER_VALIDATE_URL)) {
    $path = parse_url($icon, PHP_URL_PATH) ?: '';
    if (preg_match('~^/([^/]+)/([0-9]+)\.png$~', $path, $m)) {
        $primaryCat = $m[1];
        $primaryId  = (int)$m[2];
    }
}

// 4) Load CDN index if present (optional optimization)
$idx = load_json($CDN_INDEX);

// 5) Try primary CDN path first (if known)
if ($primaryCat && $primaryId !== null) {
    if (!$idx || cdn_has($idx, $primaryCat, $primaryId)) {
        if (fetch_cache_and_serve(cdn_url($primaryCat, $primaryId), $id)) { /* served */ }
    }
}

// 6) Try alternates for numeric id (prefer id from URL, then appId)
$tryId = $primaryId ?? $appId;
if ($tryId !== null) {
    $cats = $primaryCat ? array_merge([$primaryCat], fallback_categories($type)) : fallback_categories($type);
    $seen = [];
    foreach ($cats as $cat) {
        if (isset($seen[$cat])) continue; $seen[$cat] = true;
        if ($idx && !cdn_has($idx, $cat, $tryId)) continue; // skip if index definitively says "no"
        if (fetch_cache_and_serve(cdn_url($cat, (int)$tryId), $id)) { /* served */ }
    }
}

// 7) Fandom fallbacks (ordered candidates from includes/icon_map.php)
$candidates = nms_icon_candidates($id, $type);
foreach ($candidates as $u) {
    if (fetch_cache_and_serve($u, $id)) { /* served */ }
}

// 8) No luck — placeholder
serve_placeholder_and_exit($PLACEHOLDER);
