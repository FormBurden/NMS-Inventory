-- 20251017_0012b_recent_sort_views.sql
-- Recent-first support using snapshot_id as the timeline (no created_at required).
-- Safe & additive; does not modify existing tables or views relied on by the UI.

-- Cleanup any partials from the prior attempt (idempotent)
DROP VIEW IF EXISTS v_api_inventory_rows_active_recent;
DROP VIEW IF EXISTS v_item_last_change_active;
DROP VIEW IF EXISTS v_item_amount_seq_active;
DROP VIEW IF EXISTS v_active_snapshots;

-- 1) Active snapshots per save_root (only the columns we truly need)
CREATE ALGORITHM=UNDEFINED SQL SECURITY DEFINER VIEW v_active_snapshots AS
SELECT s.snapshot_id, s.save_root
FROM nms_snapshots s
JOIN nms_save_roots r
  ON r.save_root COLLATE utf8mb4_unicode_ci = s.save_root COLLATE utf8mb4_unicode_ci
WHERE r.is_active = 1;

-- 2) Sequence of item amounts across ALL active snapshots
CREATE ALGORITHM=UNDEFINED SQL SECURITY DEFINER VIEW v_item_amount_seq_active AS
SELECT
  s.save_root,
  i.owner_type,
  i.inventory,
  i.resource_id,
  i.snapshot_id,
  i.amount,
  LAG(i.amount) OVER (
    PARTITION BY s.save_root, i.owner_type, i.inventory, i.resource_id
    ORDER BY i.snapshot_id
  ) AS prev_amount
FROM nms_items i
JOIN v_active_snapshots s
  ON s.snapshot_id = i.snapshot_id;

-- 3) Last snapshot where a CHANGE occurred (incl. first appearance)
-- Uses snapshot_id as the time surrogate.
CREATE ALGORITHM=UNDEFINED SQL SECURITY DEFINER VIEW v_item_last_change_active AS
SELECT
  t.save_root,
  t.owner_type,
  t.inventory,
  t.resource_id,
  COALESCE(
    MAX(CASE WHEN (t.prev_amount IS NULL OR t.amount <> t.prev_amount) THEN t.snapshot_id END),
    MAX(t.snapshot_id)
  ) AS last_change_snapshot_id
FROM v_item_amount_seq_active t
GROUP BY t.save_root, t.owner_type, t.inventory, t.resource_id;

-- 4) Publish a stable sort key for the API layer
CREATE ALGORITHM=UNDEFINED SQL SECURITY DEFINER VIEW v_api_inventory_rows_active_recent AS
SELECT
  a.save_root,
  a.owner_type,
  a.inventory,
  a.resource_id,
  a.amount,
  a.item_type,
  lc.last_change_snapshot_id,
  CAST(lc.last_change_snapshot_id AS UNSIGNED) AS last_change_sort_key
FROM v_api_inventory_rows_active a
LEFT JOIN v_item_last_change_active lc
  ON lc.save_root   = a.save_root
 AND lc.owner_type  = a.owner_type
 AND lc.inventory   = a.inventory
 AND lc.resource_id = a.resource_id;
