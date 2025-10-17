-- 20251016_0011_fix_views_owner_and_ledger.sql
-- Unifies view columns, fixes collation joins, and ensures ledger table exists.

-- 0) Create minimal ledger table so "recent-first" queries work even if empty
CREATE TABLE IF NOT EXISTS nms_ledger_deltas (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  resource_id  VARCHAR(64)     NOT NULL,
  owner_type   VARCHAR(32)     NOT NULL,
  delta        INT             NULL,
  applied_at   DATETIME        NOT NULL,
  snapshot_id  BIGINT UNSIGNED NULL,
  save_root    VARCHAR(128)    NULL,
  PRIMARY KEY (id),
  KEY idx_ledger_rt_time (resource_id, owner_type, applied_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

-- 1) Drop conflicting views to ensure clean create order
DROP VIEW IF EXISTS v_api_inventory_rows_active_combined;
DROP VIEW IF EXISTS v_api_inventory_rows_active;
DROP VIEW IF EXISTS v_api_inventory_rows_by_root;
DROP VIEW IF EXISTS v_latest_snapshot_by_root;

-- 2) Latest snapshot per save_root (unchanged logic)
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

-- 3) Rows by root WITH owner_type/inventory
--    IMPORTANT: keep owner_type, inventory exposed for API/UI tabs.
CREATE OR REPLACE VIEW v_api_inventory_rows_by_root AS
SELECT
  v.save_root,
  i.owner_type,
  i.inventory,
  i.resource_id,
  SUM(i.amount) AS amount,
  COALESCE(MAX(i.item_type), 'Unknown') AS item_type
FROM nms_items i
JOIN v_latest_snapshot_by_root v
  ON v.snapshot_id = i.snapshot_id
GROUP BY
  v.save_root,
  i.owner_type,
  i.inventory,
  i.resource_id;

-- 4) Active rows = by_root joined to active roots; normalize collations in the join
CREATE OR REPLACE VIEW v_api_inventory_rows_active AS
SELECT
  r.save_root,
  a.owner_type,
  a.inventory,
  a.resource_id,
  a.amount,
  a.item_type
FROM nms_save_roots AS r
JOIN v_api_inventory_rows_by_root AS a
  ON a.save_root COLLATE utf8mb4_unicode_ci = r.save_root COLLATE utf8mb4_unicode_ci
WHERE r.is_active = 1;

-- 5) Combined rows across all active roots (by owner_type/inventory)
CREATE OR REPLACE VIEW v_api_inventory_rows_active_combined AS
SELECT
  a.owner_type,
  a.inventory,
  a.resource_id,
  SUM(a.amount)   AS amount,
  MIN(a.item_type) AS item_type
FROM v_api_inventory_rows_active AS a
GROUP BY
  a.owner_type,
  a.inventory,
  a.resource_id;
