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
  snapshot_id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  source_path        VARCHAR(1024)   NOT NULL,
  save_root          VARCHAR(128)    NOT NULL,
  source_mtime       DATETIME        NOT NULL,
  decoded_mtime      DATETIME        NULL,
  json_sha256        CHAR(64)        NOT NULL,
  imported_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (snapshot_id),
  UNIQUE KEY uniq_snapshot (source_path, source_mtime),
  KEY idx_snap_imported (imported_at),
  KEY idx_snap_root_imported (save_root, imported_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE nms_items (
  item_id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  snapshot_id        BIGINT UNSIGNED NOT NULL,
  owner_type         VARCHAR(32)     NOT NULL,         -- SUIT, SHIP, FREIGHTER, STORAGE...
  inventory          VARCHAR(32)     NOT NULL,         -- GENERAL, TECHONLY, CARGO
  container_id       VARCHAR(64)     NOT NULL DEFAULT '',
  slot_index         INT             NOT NULL,         -- position within the container
  resource_id        VARCHAR(128)    NOT NULL,         -- e.g. ^AMMO, ^ANTIMATTER
  amount             BIGINT          NOT NULL,
  item_type          VARCHAR(32)     NOT NULL,         -- Product | Substance | Technology
  created_at         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (item_id),
  CONSTRAINT fk_items_snapshot
    FOREIGN KEY (snapshot_id) REFERENCES nms_snapshots(snapshot_id)
    ON DELETE CASCADE,
  UNIQUE KEY uniq_slot_per_snapshot (snapshot_id, owner_type, inventory, container_id, slot_index),
  KEY idx_items_resource (resource_id),
  KEY idx_items_snapshot (snapshot_id),
  KEY idx_items_owner (owner_type, inventory)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- === BEGIN restore session settings ===
SET SQL_NOTES=@OLD_SQL_NOTES;
SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS;
SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS;
-- === END restore ===

