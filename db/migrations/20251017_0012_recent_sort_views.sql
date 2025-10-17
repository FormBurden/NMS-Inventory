-- 0012: Recent-first views (idempotent, uses existing snapshot timestamps)

-- keep creation order stable
SET @OLD_SQL_NOTES=@@sql_notes; SET sql_notes=0;

DROP VIEW IF EXISTS v_item_recent_seen;
SELECT s.snapshot_id, s.save_root, s.decoded_mtime AS created_at
DROP VIEW IF EXISTS v_active_snapshots;

-- Active snapshots for the currently active save_root
CREATE ALGORITHM=UNDEFINED SQL SECURITY DEFINER VIEW v_active_snapshots AS
SELECT s.snapshot_id,
       s.save_root,
       s.decoded_mtime AS created_at
FROM nms_snapshots s
JOIN nms_save_roots r
  ON r.save_root COLLATE utf8mb4_unicode_ci = s.save_root COLLATE utf8mb4_unicode_ci
WHERE r.is_active = 1;

-- Recent "seen" timestamp per owner/inventory/resource based on most recent snapshot time
CREATE ALGORITHM=UNDEFINED SQL SECURITY DEFINER VIEW v_item_recent_seen AS
SELECT i.owner_type,
       i.inventory,
       i.resource_id,
       MAX(s.decoded_mtime) AS recent_ts
FROM nms_items i
JOIN nms_snapshots s
  ON s.snapshot_id = i.snapshot_id
GROUP BY i.owner_type, i.inventory, i.resource_id;

-- Join recent_ts onto the active inventory rows; the UI can ORDER BY recent_ts DESC when sort=recent
CREATE ALGORITHM=UNDEFINED SQL SECURITY DEFINER VIEW v_api_inventory_rows_recent AS
SELECT a.owner_type,
       a.inventory,
       a.resource_id,
       a.amount,
       COALESCE(rs.recent_ts, '1970-01-01 00:00:00') AS recent_ts
FROM v_api_inventory_rows_active a
LEFT JOIN v_item_recent_seen rs
  ON rs.owner_type = a.owner_type
 AND rs.inventory  = a.inventory
 AND rs.resource_id= a.resource_id;

SET sql_notes=@OLD_SQL_NOTES;
