<?php
// public/api/icon.php
// Usage: /api/icon.php?id=LAND2[&type=Substance|Product|Technology]
// Redirects to the correct Fandom icon (PRODUCT./SUBSTANCE./TECHNOLOGY.), with fallbacks.

declare(strict_types=1);

$idRaw = $_GET['id'] ?? '';
if ($idRaw === '') {
  http_response_code(400);
  header('Content-Type: text/plain; charset=utf-8');
  echo "Missing required query param: id\n";
  exit;
}

$id = rawurldecode($idRaw); // keep carets etc., we will re-encode later
$typeHint = strtoupper(trim((string)($_GET['type'] ?? '')));

// Build the prefix try-order
$try = [];

// If caller gives a hint, honor it first
if ($typeHint !== '') {
  if (str_starts_with($typeHint, 'SUBST'))   $try[] = 'SUBSTANCE';
  elseif (str_starts_with($typeHint, 'PROD')) $try[] = 'PRODUCT';
  elseif (str_starts_with($typeHint, 'TECH')) $try[] = 'TECHNOLOGY';
}

// Heuristics for common substance families
if (preg_match('/^(LAND|FUEL|YELLOW|WATER|AIR|GAS|CAVE|PLANT|SAND|RED|GREEN|BLUE|STELLAR|POWDER|EXOTIC)/i', $id)) {
  $try[] = 'SUBSTANCE';
}

// Reasonable default and final fallback
$try[] = 'PRODUCT';
$try[] = 'TECHNOLOGY';

// Dedup while preserving order
$try = array_values(array_unique($try));

function url_for(string $prefix, string $id): string {
  // Always encode the raw ID part (handles ^ and spaces)
  return "https://nomanssky.fandom.com/wiki/Special:FilePath/{$prefix}." . rawurlencode($id) . ".png";
}

function url_exists(string $url): bool {
  $ch = curl_init($url);
  curl_setopt_array($ch, [
    CURLOPT_NOBODY         => true,
    CURLOPT_FOLLOWLOCATION => true,  // FilePath often 302s to CDN
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT        => 4,
    CURLOPT_SSL_VERIFYPEER => true,
    CURLOPT_SSL_VERIFYHOST => 2,
    // Some hosts respond differently without UA
    CURLOPT_USERAGENT      => 'NMS-Inventory/1.0 (+icon-probe)'
  ]);
  curl_exec($ch);
  $code = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
  curl_close($ch);
  return ($code >= 200 && $code < 300);
}

// Try each prefix until one works
foreach ($try as $prefix) {
  $url = url_for($prefix, $id);
  if (url_exists($url)) {
    // Cache the redirect a bit to be nice to Fandom/CDN
    header('Cache-Control: public, max-age=86400'); // 24h
    header('Location: ' . $url, true, 302);
    exit;
  }
}

// Final fallback: local placeholder (ensure this file exists)
header('Cache-Control: public, max-age=3600');
header('Location: /assets/img/placeholder.png', true, 302);
