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
  $RID = strtoupper($resourceId);

  // Seed known common items (expand as you encounter them)
  $seed = [
    'PRODUCT.ANTIMATTER'   => 'https://nomanssky.fandom.com/wiki/Special:FilePath/PRODUCT.ANTIMATTER.png',
    'PRODUCT.WARPCELL'     => 'https://nomanssky.fandom.com/wiki/Special:FilePath/PRODUCT.WARPCELL.png',
    'PRODUCT.METALPLATING' => 'https://nomanssky.fandom.com/wiki/Special:FilePath/Product.metalplating.png',
    'SUBSTANCE.CARBON'     => 'https://nomanssky.fandom.com/wiki/Special:FilePath/Substance.carbon.png',
    'SUBSTANCE.OXYGEN'     => 'https://nomanssky.fandom.com/wiki/Special:FilePath/Substance.oxygen.png',
    'SUBSTANCE.FERRITE_DUST'=> 'https://nomanssky.fandom.com/wiki/Special:FilePath/Ferrite_Dust_Icon.png',
    'SUBSTANCE.PURE_FERRITE'=> 'https://nomanssky.fandom.com/wiki/Special:FilePath/Pure_Ferrite_Icon.png',
    'SUBSTANCE.MAGNETISED_FERRITE'=> 'https://nomanssky.fandom.com/wiki/Special:FilePath/Magnetised_Ferrite_Icon.png',
  ];
  if (isset($seed[$RID])) return $seed[$RID];

  // Fallback heuristics: try a few URL shapes
  $candidates = [];

  // If resourceType known, try Product./Substance. prefixes
  if (stripos($resourceType, 'product') !== false && !str_starts_with($RID,'PRODUCT.')) {
    $candidates[] = "https://nomanssky.fandom.com/wiki/Special:FilePath/PRODUCT.$RID.png";
    $candidates[] = "https://nomanssky.fandom.com/wiki/Special:FilePath/Product.$RID.png";
  }
  if (stripos($resourceType, 'substance') !== false && !str_starts_with($RID,'SUBSTANCE.')) {
    $candidates[] = "https://nomanssky.fandom.com/wiki/Special:FilePath/SUBSTANCE.$RID.png";
    $candidates[] = "https://nomanssky.fandom.com/wiki/Special:FilePath/Substance.$RID.png";
  }

  // Last-ditch: use resourceId as file name
  $safe = preg_replace('/[^A-Z0-9._-]+/','_', $RID);
  $candidates[] = "https://nomanssky.fandom.com/wiki/Special:FilePath/$safe.png";

  // We don’t HEAD-check (to keep it snappy). First candidate wins.
  return $candidates[0];
}
