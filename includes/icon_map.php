<?php
/**
 * External icon resolver (seed map + Fandom fallback).
 * Many product icons are available at:
 *   https://nomanssky.fandom.com/wiki/Category:Product_icons
 * We try an explicit map first; else try "Special:FilePath/<TOKEN>.png" where
 * <TOKEN> is often PRODUCT.X or Product.x depending on the asset. This won’t
 * be perfect for every id, but it gets us started and we can grow the map.
 */
function nms_icon_url(string $resourceId, string $resourceType=''): string {
  // Normalize (game IDs often start with '^')
  $RID = strtoupper(ltrim($resourceId, '^'));
  $type = strtolower($resourceType ?? '');

  // Known filename stems (extend over time)
  $alias = [
    'FERRITE_DUST'         => 'Ferrite_Dust_Icon',
    'PURE_FERRITE'         => 'Pure_Ferrite_Icon',
    'MAGNETISED_FERRITE'   => 'Magnetised_Ferrite_Icon',
    'OXYGEN'               => 'Oxygen_Icon',
    'CARBON'               => 'Carbon_Icon',
    'ANTIMATTER'           => 'Antimatter_Icon',
    'WARPCELL'             => 'Warp_Cell_Icon',
  ];
  if (isset($alias[$RID])) {
    return "https://nomanssky.fandom.com/wiki/Special:FilePath/{$alias[$RID]}.png";
  }

  // Try high-hit candidates first
  $candidates = [
    "{$RID}_Icon.png",
    "$RID.png",
  ];

  // Then namespace-style variants
  if ($type === 'product') {
    $candidates[] = "PRODUCT.$RID.png";
    $candidates[] = "Product.$RID.png";
  } elseif ($type === 'substance') {
    $candidates[] = "SUBSTANCE.$RID.png";
    $candidates[] = "Substance.$RID.png";
  }

  foreach ($candidates as $fn) {
    $safe = preg_replace('/[^A-Za-z0-9._-]+/', '_', $fn);
    // We don't HEAD-check to keep responses fast; first candidate wins
    return "https://nomanssky.fandom.com/wiki/Special:FilePath/$safe";
  }

  // Should never hit
  return "https://nomanssky.fandom.com/wiki/Special:FilePath/$RID.png";
}
