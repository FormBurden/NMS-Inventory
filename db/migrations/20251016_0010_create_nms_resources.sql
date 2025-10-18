-- 20251016_0010_create_nms_resources.sql
-- Creates resource metadata table used by inventory views/API.

CREATE TABLE IF NOT EXISTS nms_resources (
  resource_id   VARCHAR(64)  NOT NULL,
  code          VARCHAR(64)  DEFAULT NULL,
  name          VARCHAR(255) DEFAULT NULL,
  display_name  VARCHAR(255) DEFAULT NULL,
  kind          ENUM('Substance','Product','Technology') DEFAULT NULL,
  is_active     TINYINT(1)   NOT NULL DEFAULT 1,
  PRIMARY KEY (resource_id),
  KEY idx_is_active (is_active),
  KEY idx_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
ALTER TABLE nms_resources ADD COLUMN IF NOT EXISTS is_active TINYINT(1) NOT NULL DEFAULT 1;


-- Seed rows for all resource_ids we already have in nms_items so results show up immediately.
INSERT INTO nms_resources (resource_id, code, is_active)
SELECT DISTINCT i.resource_id, i.resource_id, 1
FROM nms_items AS i
WHERE i.resource_id IS NOT NULL AND i.resource_id <> ''
ON DUPLICATE KEY UPDATE
  code = VALUES(code),
  is_active = VALUES(is_active);
