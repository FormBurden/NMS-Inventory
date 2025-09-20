#!/usr/bin/env php
<?php
declare(strict_types=1);

require_once __DIR__ . '/../includes/bootstrap.php';

$cacheDir = (string)env('ICON_CACHE_DIR', project_root() . '/cache/icons');
$retDays  = (int)env('ICON_CACHE_RETENTION_DAYS', 60);
$dry      = in_array('--dry-run', $argv, true);

if (!is_dir($cacheDir)) {
    fwrite(STDERR, "[WARN] Cache dir not found: $cacheDir\n");
    exit(0);
}

$cutoff = time() - ($retDays * 86400);
$meta   = glob($cacheDir . '/*.meta') ?: [];

$deleted = 0; $kept = 0;

foreach ($meta as $metaFile) {
    $base = substr($metaFile, 0, -5); // strip ".meta"
    $bin  = $base . '.bin';
    $mt   = @filemtime($metaFile) ?: 0;
    $bt   = @filemtime($bin)       ?: 0;
    $age  = max($mt, $bt);

    if ($age > 0 && $age < $cutoff) {
        if ($dry) {
            echo "[DRY] Would delete: $bin and $metaFile\n";
        } else {
            @unlink($bin);
            @unlink($metaFile);
            echo "[DEL] $bin\n";
            echo "[DEL] $metaFile\n";
        }
        $deleted++;
    } else {
        $kept++;
    }
}

echo "[OK] Cache scan complete. kept=$kept deleted=$deleted dir=$cacheDir days=$retDays dry=" . ($dry ? '1' : '0') . "\n";
