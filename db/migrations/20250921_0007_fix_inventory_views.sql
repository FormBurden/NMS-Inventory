-- 20250921_0007_fix_inventory_views.sql
-- Ensure views used by the API expose owner_type and inventory, and support strict filtering per tab.

-- by_root: latest snapshot per root → rows with owner_type/inventory
CREATE OR REPLACE VIEW v_api_inventory_rows_by_root AS
SELECT
  ls.save_root,
  i.owner_type,
  i.inventory,
  i.resource_id,
  i.amount,
  i.item_type
FROM v_latest_snapshot_by_root AS ls
JOIN nms_items AS i
  ON i.snapshot_id = ls.snapshot_id;

-- active: only active roots (keeps owner_type/inventory visible)
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
  ON a.save_root = r.save_root
WHERE r.is_active = 1;

-- combined: sums across all active roots (still grouped by owner_type/inventory)
CREATE OR REPLACE VIEW v_api_inventory_rows_active_combined AS
SELECT
  a.owner_type,
  a.inventory,
  a.resource_id,
  SUM(a.amount) AS amount,
  MIN(a.item_type) AS item_type
FROM v_api_inventory_rows_active AS a
GROUP BY
  a.owner_type,
  a.inventory,
  a.resource_id;
