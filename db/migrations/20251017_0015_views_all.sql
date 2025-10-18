-- 20251017_0015_views_all.sql
-- Canonical API/helper views for inventory.

START TRANSACTION;

-- 1) Latest snapshot per save_root (by highest snapshot_id; created_at is present but snapshot_id ordering is robust)
DROP VIEW IF EXISTS v_latest_snapshot_by_root;
CREATE ALGORITHM=UNDEFINED SQL SECURITY DEFINER VIEW v_latest_snapshot_by_root AS
SELECT
  s.save_root,
  MAX(s.snapshot_id) AS snapshot_id
FROM nms_snapshots s
GROUP BY s.save_root;

-- 2) Aggregated rows for newest snapshot per root
DROP VIEW IF EXISTS v_api_inventory_rows_by_root;
CREATE ALGORITHM=UNDEFINED SQL SECURITY DEFINER VIEW v_api_inventory_rows_by_root AS
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
GROUP BY v.save_root, i.owner_type, i.inventory, i.resource_id;

-- 3) Active root filter
DROP VIEW IF EXISTS v_api_inventory_rows_active;
CREATE ALGORITHM=UNDEFINED SQL SECURITY DEFINER VIEW v_api_inventory_rows_active AS
SELECT
  r.save_root,
  a.owner_type,
  a.inventory,
  a.resource_id,
  a.amount,
  a.item_type
FROM nms_save_roots r
JOIN v_api_inventory_rows_by_root a
  ON a.save_root COLLATE utf8mb4_unicode_ci = r.save_root COLLATE utf8mb4_unicode_ci
WHERE r.is_active = 1;

-- 4) Active snapshots helper (exposes snapshot + timestamp for “recent” joins)
DROP VIEW IF EXISTS v_active_snapshots;
CREATE ALGORITHM=UNDEFINED SQL SECURITY DEFINER VIEW v_active_snapshots AS
SELECT
  r.save_root,
  s.snapshot_id,
  s.created_at
FROM nms_save_roots r
JOIN v_latest_snapshot_by_root v
  ON v.save_root COLLATE utf8mb4_unicode_ci = r.save_root COLLATE utf8mb4_unicode_ci
JOIN nms_snapshots s
  ON s.snapshot_id = v.snapshot_id
WHERE r.is_active = 1;

-- 5) “Recent” (by newest snapshot per root, with recent_ts for ordering)
DROP VIEW IF EXISTS v_api_inventory_rows_recent;
CREATE ALGORITHM=UNDEFINED SQL SECURITY DEFINER VIEW v_api_inventory_rows_recent AS
SELECT
  b.save_root,
  b.owner_type,
  b.inventory,
  b.resource_id,
  b.amount,
  b.item_type,
  s.created_at AS recent_ts
FROM v_api_inventory_rows_by_root b
JOIN v_latest_snapshot_by_root v
  ON v.save_root COLLATE utf8mb4_unicode_ci = b.save_root COLLATE utf8mb4_unicode_ci
JOIN nms_snapshots s
  ON s.snapshot_id = v.snapshot_id;

-- 6) “Recent” + active filter
DROP VIEW IF EXISTS v_api_inventory_rows_active_recent;
CREATE ALGORITHM=UNDEFINED SQL SECURITY DEFINER VIEW v_api_inventory_rows_active_recent AS
SELECT
  a.save_root,
  a.owner_type,
  a.inventory,
  a.resource_id,
  a.amount,
  a.item_type,
  s.created_at AS recent_ts
FROM v_api_inventory_rows_active a
JOIN v_active_snapshots s
  ON s.save_root COLLATE utf8mb4_unicode_ci = a.save_root COLLATE utf8mb4_unicode_ci;

COMMIT;
