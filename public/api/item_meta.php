<?php
// public/api/item_meta.php
// Usage: /api/item_meta.php?search=LAUNCHFUEL
// Proxies AssistantNMS catalogue and ALWAYS returns JSON (even on errors).

declare(strict_types=1);

// --- Hardening: never echo PHP warnings/notices into the JSON ---
@ini_set('display_errors', '0');
@ini_set('html_errors', '0');
error_reporting(E_ALL & ~E_NOTICE & ~E_WARNING);
header_remove('X-Powered-By');
header('Content-Type: application/json; charset=utf-8');

// Small helper to send compact JSON and stop execution
function respond_json(array $payload, int $status = 200): void {
  if (function_exists('ob_get_length') && ob_get_length()) { @ob_end_clean(); }
  http_response_code($status);
  // Keep it compact; upstream responses can be large.
  echo json_encode($payload, JSON_UNESCAPED_SLASHES);
  exit;
}

$search = isset($_GET['search']) ? trim((string)$_GET['search']) : '';
if ($search === '') {
  respond_json(['ok' => false, 'error' => 'Missing query param: search'], 400);
}

$target = 'https://api.nmsassistant.com/public/catalogue/find?search=' . rawurlencode($search);

// Fetch upstream (follow redirects; accept JSON even if text/plain)
$ch = curl_init($target);
curl_setopt_array($ch, [
  CURLOPT_RETURNTRANSFER => true,
  CURLOPT_FOLLOWLOCATION => true,
  CURLOPT_CONNECTTIMEOUT => 5,
  CURLOPT_TIMEOUT        => 10,
  CURLOPT_SSL_VERIFYPEER => true,
  CURLOPT_SSL_VERIFYHOST => 2,
  CURLOPT_USERAGENT      => 'NMS-Inventory/1.0 (+item-meta-proxy)',
  CURLOPT_HTTPHEADER     => [
    'Accept: application/json, text/plain;q=0.9, */*;q=0.1',
  ],
]);
$body = curl_exec($ch);
$code = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
$ctype = (string)curl_getinfo($ch, CURLINFO_CONTENT_TYPE);
$cerr  = curl_error($ch);
curl_close($ch);

// Network or cURL failure
if ($body === false) {
  respond_json(['ok' => false, 'error' => 'Upstream request failed', 'curl' => $cerr], 502);
}

// Try to decode whatever we got; if it’s valid JSON, pass it through (normalized)
$decoded = json_decode($body, true);
if (json_last_error() === JSON_ERROR_NONE && is_array($decoded)) {
  // Success: cache mildly to avoid hammering the API
  header('Cache-Control: public, max-age=21600'); // 6h
  // Normalize into object to keep jq happy even if upstream shape changes slightly
  respond_json($decoded, ($code >= 200 && $code < 300) ? 200 : 502);
}

// Not JSON: return an error envelope with a short snippet for debugging
$snippet = trim(preg_replace('/\s+/', ' ', strip_tags(substr($body, 0, 400))));
respond_json([
  'ok'      => false,
  'error'   => 'Upstream returned non-JSON',
  'status'  => $code,
  'ctype'   => $ctype,
  'snippet' => $snippet,
], 502);
