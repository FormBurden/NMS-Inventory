-- 20251016_0009_create_core_tables.sql
-- Core schema required by views and pipeline:
--   nms_snapshots, nms_items, nms_save_roots, nms_settings

CREATE TABLE IF NOT EXISTS `nms_snapshots` (
  `snapshot_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `save_root`   VARCHAR(64) NOT NULL,
  `imported_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `source_file` VARCHAR(255) NOT NULL DEFAULT '',
  PRIMARY KEY (`snapshot_id`),
  KEY `idx_snapshots_save_root` (`save_root`),
  KEY `idx_snapshots_imported_at` (`imported_at`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `nms_items` (
  `id`           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `snapshot_id`  BIGINT UNSIGNED NOT NULL,
  `owner_type`   ENUM('PLAYER','SHIP','VEHICLE','FREIGHTER','STORAGE') NOT NULL,
  `owner_index`  INT NULL,
  `owner_name`   VARCHAR(128) NOT NULL DEFAULT '',
  `inventory`    ENUM('GENERAL','CARGO') NOT NULL,
  `slot_x`       INT NOT NULL,
  `slot_y`       INT NOT NULL,
  `resource_id`  VARCHAR(64) NOT NULL,
  `item_type`    ENUM('Product','Substance','Technology','Unknown') NOT NULL DEFAULT 'Unknown',
  `amount`       INT NOT NULL,
  `max_amount`   INT NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_items_snapshot` (`snapshot_id`),
  KEY `idx_items_owner` (`owner_type`, `owner_index`),
  KEY `idx_items_inventory` (`inventory`),
  KEY `idx_items_resource` (`resource_id`),
  CONSTRAINT `fk_items_snapshot`
    FOREIGN KEY (`snapshot_id`) REFERENCES `nms_snapshots` (`snapshot_id`)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `nms_save_roots` (
  `save_root` VARCHAR(64) NOT NULL,
  `is_active` TINYINT(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (`save_root`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `nms_settings` (
  `key`   VARCHAR(128) NOT NULL,
  `value` TEXT NOT NULL,
  PRIMARY KEY (`key`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;
