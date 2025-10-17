-- 20251017_0013_fix_items_item_type.sql
-- Normalize nms_items.item_type to a flexible text type compatible with importer output.

START TRANSACTION;

-- If the column exists but is ENUM/too short, widen it to VARCHAR(32).
-- utf8mb4_uca1400_ai_ci matches your recent migrations/views.
ALTER TABLE nms_items
  MODIFY COLUMN item_type VARCHAR(32) NOT NULL
  COLLATE utf8mb4_uca1400_ai_ci;

COMMIT;
