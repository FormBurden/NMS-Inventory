-- === BEGIN FK- and view-safe reset header ===
SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0;
SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0;
SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0;

-- Drop dependent views first (most dependent → least)
DROP VIEW IF EXISTS v_api_inventory_rows_active_combined;
DROP VIEW IF EXISTS v_api_inventory_rows_active;
DROP VIEW IF EXISTS v_api_inventory_rows_by_root;
DROP VIEW IF EXISTS v_latest_snapshot_by_root;

-- Drop tables (children before parents)
DROP TABLE IF EXISTS nms_items;
DROP TABLE IF EXISTS nms_ledger_deltas;
DROP TABLE IF EXISTS nms_import_log;
DROP TABLE IF EXISTS nms_save_roots;
DROP TABLE IF EXISTS nms_settings;
DROP TABLE IF EXISTS nms_snapshots;
-- === END header ===


CREATE TABLE nms_snapshots (
  snapshot_id     INT UNSIGNED NOT NULL AUTO_INCREMENT,
  source_path     VARCHAR(512) NOT NULL,
  save_root       VARCHAR(128) NOT NULL,
  source_mtime    DATETIME NULL,
  decoded_mtime   DATETIME NULL,
  json_sha256     CHAR(64) NOT NULL,
  imported_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (snapshot_id),
  UNIQUE KEY uniq_snapshot (save_root, source_mtime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE nms_items (
  item_id       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  snapshot_id   INT  UNSIGNED NOT NULL,
  owner_type    ENUM('SUIT','SHIP','FREIGHTER','VEHICLE','STORAGE','PET','BASE','UNKNOWN') NOT NULL,
  inventory     ENUM('GENERAL','TECHONLY','CARGO') NOT NULL,
  container_id  VARCHAR(64) NOT NULL DEFAULT '',
  slot_index    INT  UNSIGNED NOT NULL,
  resource_id   VARCHAR(64) NOT NULL,
  amount        INT  UNSIGNED NOT NULL,
  item_type     ENUM('Product','Substance','Technology') NOT NULL,
  PRIMARY KEY (item_id),
  KEY idx_snapshot (snapshot_id),
  KEY idx_resource (resource_id),
  CONSTRAINT fk_items_snapshot
    FOREIGN KEY (snapshot_id) REFERENCES nms_snapshots(snapshot_id)
    ON DELETE CASCADE,
  UNIQUE KEY uniq_slot_per_snapshot
    (snapshot_id, owner_type, inventory, container_id, slot_index)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- === BEGIN restore session settings ===
SET SQL_NOTES=@OLD_SQL_NOTES;
SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS;
SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS;
-- === END restore ===

