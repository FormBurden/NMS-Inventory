-- db/migrations/20250921_0006_collation_fix.sql
-- Normalize collations to utf8mb4_unicode_ci and (re)create required tables/views

SET NAMES utf8mb4;
SET time_zone = '+00:00';

-- 0) Ensure database default is consistent (safe even if already set)
ALTER DATABASE `nms_database`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

-- 1) CREATE TABLEs that might be missing (idempotent)
CREATE TABLE IF NOT EXISTS `nms_save_roots` (
  `save_root`  VARCHAR(128) NOT NULL,
  `is_active`  TINYINT(1) NOT NULL DEFAULT 1,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`save_root`)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 2) Convert key tables to the normalized collation (safe to re-run)
ALTER TABLE `nms_snapshots`
  CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

ALTER TABLE `nms_items`
  CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

ALTER TABLE `nms_save_roots`
  CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 3) (Re)create helper view: latest snapshot per save_root
DROP VIEW IF EXISTS `v_latest_snapshot_by_root`;
CREATE OR REPLACE VIEW `v_latest_snapshot_by_root` AS
SELECT
  s.save_root AS save_root,
  MAX(s.snapshot_id) AS snapshot_id
FROM `nms_snapshots` s
GROUP BY s.save_root;

-- 4) Rows per root from the latest snapshot of each root
DROP VIEW IF EXISTS `v_api_inventory_rows_by_root`;
CREATE OR REPLACE VIEW `v_api_inventory_rows_by_root` AS
SELECT
  v.save_root AS save_root,
  i.resource_id AS resource_id,
  SUM(i.amount) AS amount,
  COALESCE(MAX(i.item_type), 'Unknown') AS item_type
FROM `nms_items` i
JOIN `v_latest_snapshot_by_root` v
  ON v.snapshot_id = i.snapshot_id
GROUP BY v.save_root, i.resource_id;

-- 5) Active roots only (determined by nms_save_roots.is_active)
DROP VIEW IF EXISTS `v_api_inventory_rows_active`;
CREATE OR REPLACE VIEW `v_api_inventory_rows_active` AS
SELECT
  r.save_root AS save_root,
  a.resource_id,
  a.amount,
  a.item_type
FROM `nms_save_roots` r
JOIN `v_api_inventory_rows_by_root` a
  ON a.save_root = r.save_root
WHERE r.is_active = 1;

-- 6) Combined totals across all active roots
DROP VIEW IF EXISTS `v_api_inventory_rows_active_combined`;
CREATE OR REPLACE VIEW `v_api_inventory_rows_active_combined` AS
SELECT
  resource_id,
  SUM(amount) AS amount,
  COALESCE(MAX(item_type), 'Unknown') AS item_type
FROM `v_api_inventory_rows_active`
GROUP BY resource_id;
