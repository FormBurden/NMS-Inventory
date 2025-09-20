<?php
declare(strict_types=1);

// Image proxy & disk cache for NMS icons.
// Serve from local cache if present (no upstream pull).
// Adds ETag/Last-Modified so repeat loads are 304 from browser.

require_once __DIR__ . '/../../includes/bootstrap.php';
require_once __DIR__ . '/../../includes/icon_map.php';

$id   = isset($_GET['id'])   ? (string)$_GET['id']   : '';
$type = isset($_GET['type']) ? (string)$_GET['type'] : '';
if ($id === '') {
    http_response_code(400);
    header('Content-Type: text/plain; charset=utf-8');
    echo "Missing id";
    exit;
}

$cacheDir       = (string)env('ICON_CACHE_DIR', project_root() . '/cache/icons');
$browserMaxAge  = (int)env('ICON_CACHE_BROWSER_MAX_AGE', 2592000); // 30d
if (!is_dir($cacheDir)) @mkdir($cacheDir, 0775, true);

$candidates = nms_icon_candidates($id, $type);

// Helper to emit headers for a cached file and optionally short-circuit 304/HEAD.
$serveCached = function (string $dataFile, string $contentType) use ($browserMaxAge) {
    $mtime = @filemtime($dataFile) ?: time();
    $size  = @filesize($dataFile) ?: 0;
    $etag  = sprintf('W/"%s-%d"', substr(sha1($dataFile.$mtime.$size), 0, 16), $size);
    $last  = gmdate('D, d M Y H:i:s', $mtime) . ' GMT';

    // Conditional requests
    $ifNone = $_SERVER['HTTP_IF_NONE_MATCH'] ?? '';
    $ifMod  = $_SERVER['HTTP_IF_MODIFIED_SINCE'] ?? '';
    if ($ifNone === $etag || ($ifMod && strtotime($ifMod) >= $mtime)) {
        header('ETag: ' . $etag);
        header('Last-Modified: ' . $last);
        header('Cache-Control: public, max-age=' . $browserMaxAge . ', immutable');
        http_response_code(304);
        return true;
    }

    header('Content-Type: ' . ($contentType ?: 'application/octet-stream'));
    header('Content-Length: ' . $size);
    header('ETag: ' . $etag);
    header('Last-Modified: ' . $last);
    header('Cache-Control: public, max-age=' . $browserMaxAge . ', immutable');
    header('Vary: Accept');

    if ($_SERVER['REQUEST_METHOD'] === 'HEAD') return true;

    readfile($dataFile);
    return true;
};

foreach ($candidates as $url) {
    $key      = sha1($url);
    $dataFile = "$cacheDir/$key.bin";
    $metaFile = "$cacheDir/$key.meta";

    // Serve from cache if present (never re-pull upstream here).
    if (is_file($dataFile) && is_file($metaFile)) {
        $meta = @json_decode((string)file_get_contents($metaFile), true) ?: [];
        $ctype = $meta['content_type'] ?? 'application/octet-stream';
        $serveCached($dataFile, $ctype);
        exit;
    }

    // Not cached yet: fetch once, cache, and return
    $ok = false; $bytes = ''; $ctype = null;
    if (function_exists('curl_init')) {
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_FOLLOWLOCATION => true,
            CURLOPT_MAXREDIRS      => 5,
            CURLOPT_CONNECTTIMEOUT => 5,
            CURLOPT_TIMEOUT        => 10,
            CURLOPT_USERAGENT      => 'NMS-Inventory-IconProxy/1.0 (+https://github.com/FormBurden/NMS-Inventory)',
            CURLOPT_HTTPHEADER     => ['Accept: image/avif,image/webp,image/apng,image/*,*/*;q=0.8'],
        ]);
        $bytes = (string)curl_exec($ch);
        $http  = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $ctype = (string)curl_getinfo($ch, CURLINFO_CONTENT_TYPE);
        curl_close($ch);
        $ok = ($http >= 200 && $http < 300) && $bytes !== '';
    } else {
        $ctx = stream_context_create([
            'http' => [
                'method'  => 'GET',
                'header'  => "User-Agent: NMS-Inventory-IconProxy/1.0\r\nAccept: image/*\r\n",
                'timeout' => 10,
                'follow_location' => 1,
                'max_redirects'   => 5,
            ],
        ]);
        $bytes = @file_get_contents($url, false, $ctx);
        $ok    = $bytes !== false && $bytes !== '';
        if ($ok) {
            $finfo = new finfo(FILEINFO_MIME_TYPE);
            $ctype = $finfo->buffer($bytes) ?: 'application/octet-stream';
        }
    }

    if ($ok) {
        @file_put_contents($dataFile, $bytes);
        @file_put_contents($metaFile, json_encode(['content_type' => $ctype], JSON_UNESCAPED_SLASHES));
        // Serve from fresh cache (also sets ETag/Last-Modified)
        $serveCached($dataFile, $ctype);
        exit;
    }
}

// Fallback SVG placeholder with the ID
$disp = ltrim(strtoupper($id), '^');
$svg  = '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96">'
      . '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
      . '<stop offset="0" stop-color="#222"/><stop offset="1" stop-color="#444"/></linearGradient></defs>'
      . '<rect width="96" height="96" rx="12" fill="url(#g)"/>'
      . '<text x="48" y="54" font-family="monospace" font-size="18" fill="#eaeaea" text-anchor="middle">'.$disp.'</text>'
      . '</svg>';
header('Content-Type: image/svg+xml; charset=utf-8');
header('Cache-Control: public, max-age=3600');
echo $svg;
