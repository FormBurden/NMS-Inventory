-- 20251016_0012_create_initial_items.sql
-- Baseline table for initial inventory snapshots used by the ledger step.

CREATE TABLE IF NOT EXISTS `nms_initial_items` (
  `snapshot_ts`  DATETIME NOT NULL,
  `owner_type`   ENUM('PLAYER','SHIP','VEHICLE','FREIGHTER','STORAGE') NOT NULL,
  `owner_index`  INT NULL,
  `owner_name`   VARCHAR(128) NOT NULL DEFAULT '',
  `inventory`    ENUM('GENERAL','CARGO') NOT NULL,
  `slot_x`       INT NOT NULL,
  `slot_y`       INT NOT NULL,
  `resource_id`  VARCHAR(64) NOT NULL,
  `resource_type` ENUM('Product','Substance','Technology') NOT NULL,
  `amount`       INT NOT NULL,
  `max_amount`   INT NOT NULL,
  `source_file`  VARCHAR(255) NOT NULL,
  INDEX (`snapshot_ts`),
  INDEX (`owner_type`),
  INDEX (`inventory`),
  INDEX (`resource_id`),
  INDEX (`resource_type`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_uca1400_ai_ci;
