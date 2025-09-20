-- db/migrations/20250920_0001_core.sql
-- Core schema for NMS-Inventory (MariaDB 10.6+ / 10.11+)

SET NAMES utf8mb4;
SET time_zone = '+00:00';

-- Snapshots: each decoded save snapshot you import
CREATE TABLE IF NOT EXISTS nms_snapshots (
  snapshot_id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  source_path        VARCHAR(1024)   NOT NULL,
  save_root          VARCHAR(128)    NOT NULL,         -- e.g. st_7656...
  source_mtime       DATETIME        NOT NULL,         -- file mtime (UTC)
  decoded_mtime      DATETIME        NULL,             -- when decoded to JSON (UTC)
  json_sha256        CHAR(64)        NOT NULL,         -- hash of decoded JSON
  imported_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (snapshot_id),
  UNIQUE KEY uniq_snapshot (source_path, source_mtime),
  KEY idx_snap_imported (imported_at),
  KEY idx_snap_root_imported (save_root, imported_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Items extracted from a snapshot (one row per slot)
CREATE TABLE IF NOT EXISTS nms_items (
  item_id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  snapshot_id        BIGINT UNSIGNED NOT NULL,
  owner_type         VARCHAR(32)     NOT NULL,         -- e.g. SUIT, SHIP, FREIGHTER, STORAGE
  inventory          VARCHAR(32)     NOT NULL,         -- e.g. GENERAL, TECHONLY, CARGO
  container_id       VARCHAR(64)     NOT NULL DEFAULT '', -- storage index / ship id, etc.
  slot_index         INT             NOT NULL,         -- position within the container
  resource_id        VARCHAR(128)    NOT NULL,         -- e.g. ^AMMO, ^ANTIMATTER
  amount             BIGINT          NOT NULL,         -- quantity at that slot
  item_type          VARCHAR(32)     NOT NULL,         -- "Product" | "Substance" | "Technology" (if known)
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

-- Import log: prevent double-inserting the same decoded file
CREATE TABLE IF NOT EXISTS nms_import_log (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  source_path        VARCHAR(1024)   NOT NULL,
  source_mtime       DATETIME        NOT NULL,
  decoded_sha256     CHAR(64)        NOT NULL,
  imported_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uniq_import (source_path, source_mtime),
  KEY idx_import_time (imported_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Materialized “current totals” (optional cache for fast API)
CREATE TABLE IF NOT EXISTS nms_inventory_totals (
  resource_id        VARCHAR(128)    NOT NULL,
  amount             BIGINT          NOT NULL,
  item_type          VARCHAR(32)     NOT NULL,
  computed_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (resource_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Ledger deltas between two snapshots (what changed)
CREATE TABLE IF NOT EXISTS nms_ledger_deltas (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  from_snapshot_id   BIGINT UNSIGNED NOT NULL,
  to_snapshot_id     BIGINT UNSIGNED NOT NULL,
  resource_id        VARCHAR(128)    NOT NULL,
  delta              BIGINT          NOT NULL,
  computed_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_ledger_resource (resource_id),
  CONSTRAINT fk_ledger_from
    FOREIGN KEY (from_snapshot_id) REFERENCES nms_snapshots(snapshot_id)
    ON DELETE CASCADE,
  CONSTRAINT fk_ledger_to
    FOREIGN KEY (to_snapshot_id) REFERENCES nms_snapshots(snapshot_id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
