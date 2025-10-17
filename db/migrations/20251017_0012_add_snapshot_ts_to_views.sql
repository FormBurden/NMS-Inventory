-- 20251017_0012_add_snapshot_ts_to_views.sql
-- Provide a reusable view of the latest active snapshot timestamp per save_root.

DROP VIEW IF EXISTS v_active_snapshot_ts;

CREATE ALGORITHM=UNDEFINED SQL SECURITY DEFINER VIEW v_active_snapshot_ts AS
SELECT
  s.save_root,
  MAX(s.decoded_mtime) AS snapshot_ts
FROM nms_snapshots s
JOIN nms_save_roots r
  ON r.save_root COLLATE utf8mb4_unicode_ci = s.save_root COLLATE utf8mb4_unicode_ci
WHERE r.is_active = 1
GROUP BY s.save_root;

-- No changes to base inventory views; API will LEFT JOIN this view when needed.
