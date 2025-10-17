-- 20251017_0012_recent_sort_views.sql
-- Adds recent-sort support without altering existing views.

-- 1) Convenience: active snapshots per save_root
DROP VIEW IF EXISTS v_active_snapshots;
CREATE ALGORITHM=UNDEFINED SQL SECURITY DEFINER VIEW v_active_snapshots AS
SELECT s.snapshot_id, s.save_root, s.imported_at
FROM nms_snapshots s
JOIN nms_save_roots r
  ON r.save_root COLLATE utf8mb4_unicode_ci = s.save_root COLLATE utf8mb4_unicode_ci
WHERE r.is_active = 1;

-- 2) Sequence of item amounts across ALL snapshots for active roots
DROP VIEW IF EXISTS v_item_amount_seq_active;
CREATE ALGORITHM=UNDEFINED SQL SECURITY DEFINER VIEW v_item_amount_seq_active AS
SELECT
  s.save_root,
  i.owner_type,
  i.inventory,
  i.resource_id,
  i.snapshot_id,
  s.imported_at,
  i.amount,
  LAG(i.amount) OVER (
    PARTITION BY s.save_root, i.owner_type, i.inventory, i.resource_id
    ORDER BY i.snapshot_id
  ) AS prev_amount
FROM nms_items i
JOIN v_active_snapshots s
  ON s.snapshot_id = i.snapshot_id;

-- 3) Last snapshot where a CHANGE occurred (incl. first appearance)
-- If imported_at is NULL, we’ll fall back to snapshot_id.
DROP VIEW IF EXISTS v_item_last_change_active;
CREATE ALGORITHM=UNDEFINED SQL SECURITY DEFINER VIEW v_item_last_change_active AS
SELECT
  t.save_root,
  t.owner_type,
  t.inventory,
  t.resource_id,
  -- last_change_snapshot_id: the highest snapshot_id where amount changed (or first row)
  COALESCE(
    MAX(CASE WHEN (t.prev_amount IS NULL OR t.amount <> t.prev_amount) THEN t.snapshot_id END),
    MAX(t.snapshot_id)
  ) AS last_change_snapshot_id,
  -- last_change_at: imported_at for that snapshot if available
  SUBSTRING_INDEX(
    GROUP_CONCAT(CASE WHEN (t.prev_amount IS NULL OR t.amount <> t.prev_amount)
                      THEN IFNULL(UNIX_TIMESTAMP(t.imported_at), NULL) END
                ORDER BY t.snapshot_id DESC SEPARATOR ','),
    ',', 1
  ) AS last_change_at_unix
FROM v_item_amount_seq_active t
GROUP BY t.save_root, t.owner_type, t.inventory, t.resource_id;

-- 4) Publish a stable sort key we can use from the API
-- We re-join to the current active inventory rows (your existing view).
DROP VIEW IF EXISTS v_api_inventory_rows_active_recent;
CREATE ALGORITHM=UNDEFINED SQL SECURITY DEFINER VIEW v_api_inventory_rows_active_recent AS
SELECT
  a.save_root,
  a.owner_type,
  a.inventory,
  a.resource_id,
  a.amount,
  a.item_type,
  lc.last_change_snapshot_id,
  CAST(COALESCE(lc.last_change_at_unix, lc.last_change_snapshot_id) AS UNSIGNED) AS last_change_sort_key
FROM v_api_inventory_rows_active a
LEFT JOIN v_item_last_change_active lc
  ON lc.save_root = a.save_root
 AND lc.owner_type = a.owner_type
 AND lc.inventory = a.inventory
 AND lc.resource_id = a.resource_id;
