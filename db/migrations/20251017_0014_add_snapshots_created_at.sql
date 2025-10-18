-- 20251017_0014_add_snapshots_created_at.sql
-- Adds created_at to nms_snapshots for “recent” and age calculations.

START TRANSACTION;

ALTER TABLE nms_snapshots
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL
    DEFAULT CURRENT_TIMESTAMP;

-- Optional backfill if your engine doesn’t set DEFAULT retroactively for old rows:
UPDATE nms_snapshots
   SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP);

COMMIT;
