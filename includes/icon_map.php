<?php
declare(strict_types=1);

/**
 * Build an ordered list of candidate external icon URLs for a given resource.
 * We try the most-specific patterns first, then generic fallbacks.
 */
function nms_icon_candidates(string $resourceId, string $type = ''): array {
    $rid  = strtoupper($resourceId);
    $ridT = ltrim($rid, '^'); // display-ish

    $base = 'https://nomanssky.fandom.com/wiki/Special:FilePath/';
    $out  = [];

    // 1) Product items frequently exist as PRODUCT.^FOO.png (caret kept)
    if (strcasecmp($type, 'Product') === 0) {
        $out[] = $base . 'PRODUCT.' . rawurlencode($rid) . '.png';   // e.g. PRODUCT.%5EAMMO.png
        $out[] = $base . 'PRODUCT.' . rawurlencode($ridT) . '.png';  // e.g. PRODUCT.AMMO.png
    }

    // 2) Technology sometimes exists as TECHNOLOGY.^FOO.png
    if (strcasecmp($type, 'Technology') === 0) {
        $out[] = $base . 'TECHNOLOGY.' . rawurlencode($rid) . '.png';
        $out[] = $base . 'TECHNOLOGY.' . rawurlencode($ridT) . '.png';
    }

    // 3) Generic “NAME_Icon.png” is common across types
    $out[] = $base . rawurlencode($ridT . '_Icon.png'); // e.g. OXYGEN_Icon.png
    // 3.1) Hash-normalized variants for procedurals like PROC_PLNT#17714
    $ridHashless = preg_replace('/#.*/', '', $ridT);  // PROC_PLNT
    $ridNoHash   = str_replace('#', '', $ridT);       // PROC_PLNT17714
    $ridUnders   = str_replace('#', '_', $ridT);      // PROC_PLNT_17714

    // Common wiki filename shapes
    $out[] = $base . rawurlencode($ridHashless . '_Icon.png');
    $out[] = $base . rawurlencode($ridNoHash   . '_Icon.png');
    $out[] = $base . rawurlencode($ridUnders   . '_Icon.png');

    if (strcasecmp($type, 'Product') === 0) {
        $out[] = $base . 'PRODUCT.'   . rawurlencode($ridHashless) . '.png';
        $out[] = $base . 'PRODUCT.'   . rawurlencode($ridNoHash)   . '.png';
        $out[] = $base . 'PRODUCT.'   . rawurlencode($ridUnders)   . '.png';
    } elseif (strcasecmp($type, 'Technology') === 0) {
        $out[] = $base . 'TECHNOLOGY.' . rawurlencode($ridHashless) . '.png';
        $out[] = $base . 'TECHNOLOGY.' . rawurlencode($ridNoHash)   . '.png';
        $out[] = $base . 'TECHNOLOGY.' . rawurlencode($ridUnders)   . '.png';
    }


    // 4) As a last resort, try the raw (with caret) “_Icon” shape
    $out[] = $base . rawurlencode($rid . '_Icon.png');  // e.g. ^AMMO_Icon.png

    // De-duplicate while preserving order
    $uniq = [];
    foreach ($out as $u) {
        if (!isset($uniq[$u])) $uniq[$u] = true;
    }
    return array_keys($uniq);
}

/**
 * For legacy callers that want a single URL, return the first candidate.
 */
function nms_icon_url(string $resourceId, string $type = ''): string {
    $candidates = nms_icon_candidates($resourceId, $type);
    return $candidates[0] ?? '';
}
