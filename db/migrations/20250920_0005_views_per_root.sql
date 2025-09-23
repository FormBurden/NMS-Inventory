-- Latest snapshot per save_root
CREATE OR REPLACE VIEW v_latest_snapshot_by_root AS
SELECT save_root, snapshot_id
FROM (
  SELECT
    save_root,
    snapshot_id,
    ROW_NUMBER() OVER (PARTITION BY save_root ORDER BY imported_at DESC, snapshot_id DESC) AS rn
  FROM nms_snapshots
) x
WHERE rn = 1;

-- Per-root inventory rows (API-friendly)
CREATE OR REPLACE VIEW v_api_inventory_rows_by_root AS
SELECT
  v.save_root,
  i.resource_id,
  SUM(i.amount) AS amount,
  COALESCE(MAX(i.item_type), 'Unknown') AS item_type
FROM nms_items i
JOIN v_latest_snapshot_by_root v ON v.snapshot_id = i.snapshot_id
GROUP BY v.save_root, i.resource_id;

-- Roots registry (choose which roots count)
CREATE TABLE IF NOT EXISTS nms_save_roots (
  save_root    VARCHAR(128) NOT NULL,
  is_active    TINYINT(1)   NOT NULL DEFAULT 1,
  display_name VARCHAR(255) NULL,
  created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (save_root)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Active only
CREATE OR REPLACE VIEW v_api_inventory_rows_active AS
SELECT r.save_root, a.resource_id, a.amount, a.item_type
FROM nms_save_roots r
JOIN v_api_inventory_rows_by_root a ON a.save_root COLLATE utf8mb4_unicode_ci = r.save_root COLLATE utf8mb4_unicode_ci
WHERE r.is_active = 1;

-- Combined (single total across active roots)
CREATE OR REPLACE VIEW v_api_inventory_rows_active_combined AS
SELECT
  resource_id,
  SUM(amount) AS amount,
  COALESCE(MAX(item_type), 'Unknown') AS item_type
FROM v_api_inventory_rows_active
GROUP BY resource_id;
