-- Create a single-row table for UI settings
CREATE TABLE IF NOT EXISTS `nms_settings` (
  `id` TINYINT UNSIGNED NOT NULL PRIMARY KEY DEFAULT 1,
  `settings_json` LONGTEXT NOT NULL,
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CHECK (JSON_VALID(`settings_json`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO `nms_settings` (`id`, `settings_json`)
VALUES (1, JSON_OBJECT())
ON DUPLICATE KEY UPDATE id = id;
