<?php
declare(strict_types=1);

error_reporting(E_ALL);
ini_set('display_errors', '1');

/**
 * Resolve project root (parent of /includes).
 */
function project_root(): string {
    return dirname(__DIR__);
}

/**
 * Load .env once into memory.
 */
function load_env_once(): array {
    static $env = null;
    if ($env !== null) return $env;

    $env = [];
    $file = project_root() . '/.env';
    if (is_file($file)) {
        $lines = file($file, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
        foreach ($lines as $line) {
            $line = ltrim($line);
            if ($line === '' || $line[0] === '#') continue;
            if (!str_contains($line, '=')) continue;
            [$k, $v] = explode('=', $line, 2);
            $env[trim($k)] = trim($v);
        }
    }
    return $env;
}

/**
 * env('KEY','default') -> value
 * Prefers .env contents, falls back to real environment variable.
 */
function env(string $key, $default = null) {
    $map = load_env_once();
    if (array_key_exists($key, $map)) return $map[$key];
    $val = getenv($key);
    return ($val !== false) ? $val : $default;
}
