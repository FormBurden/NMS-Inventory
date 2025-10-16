-- db/migrations/20250921_0008_resources_catalog.sql
-- Resources catalog used by API joins for display names/icons/types.
-- Safe to run multiple times (IF NOT EXISTS; INSERT IGNORE).

SET NAMES utf8mb4;
SET time_zone = '+00:00';

CREATE TABLE IF NOT EXISTS `nms_resources` (
  `resource_id`  VARCHAR(128)  NOT NULL,
  `code`         VARCHAR(128)  NOT NULL DEFAULT '',
  `name`         VARCHAR(255)  NULL,
  `display_name` VARCHAR(255)  NULL,
  `icon_url`     VARCHAR(1024) NULL,
  `item_type`    VARCHAR(32)   NULL,
  PRIMARY KEY (`resource_id`),
  KEY `idx_res_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Optional minimal seed so UI has human names immediately.
-- Remove or extend later with your real catalog sync.
INSERT IGNORE INTO `nms_resources`
(`resource_id`, `code`, `name`, `display_name`, `icon_url`, `item_type`)
VALUES
  ('^AMMO','^AMMO','Ammunition','Ammunition',NULL,'Substance'),
  ('^ANTIMATTER','^ANTIMATTER','Antimatter','Antimatter',NULL,'Product');
