#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"
[[ -f "$ENV_FILE" ]] || { echo "Missing .env at $ENV_FILE"; exit 2; }

set -a; source "$ENV_FILE"; set +a

mysql_exec() {
  MYSQL_PWD="$NMS_DB_PASS" mariadb -h "$NMS_DB_HOST" -P "$NMS_DB_PORT" -u "$NMS_DB_USER" -N -B -e "$1"
}
db_exec() {
  MYSQL_PWD="$NMS_DB_PASS" mariadb -h "$NMS_DB_HOST" -P "$NMS_DB_PORT" -u "$NMS_DB_USER" -D "$NMS_DB_NAME" -N -B -e "$1"
}

mysql_exec "DROP DATABASE IF EXISTS \`$NMS_DB_NAME\`;
CREATE DATABASE \`$NMS_DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

db_exec "
CREATE TABLE nms_snapshots (
  snapshot_id    INT UNSIGNED NOT NULL AUTO_INCREMENT,
  source_path    VARCHAR(512) NOT NULL,
  save_root      VARCHAR(64)  NOT NULL,
  source_mtime   DATETIME     NOT NULL,
  decoded_mtime  DATETIME     DEFAULT NULL,
  json_sha256    CHAR(64)     NOT NULL,
  imported_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  notes          VARCHAR(255) DEFAULT NULL,
  PRIMARY KEY (snapshot_id),
  UNIQUE KEY uniq_source (source_path, source_mtime),
  KEY (imported_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE nms_items (
  item_id      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  snapshot_id  INT UNSIGNED    NOT NULL,
  owner_type   ENUM('SUIT','SHIP','FREIGHTER','VEHICLE','STORAGE','PET','BASE','UNKNOWN') NOT NULL,
  inventory    ENUM('GENERAL','TECHONLY','CARGO') NOT NULL,
  container_id VARCHAR(64)     NOT NULL,
  slot_index   INT UNSIGNED    NOT NULL,
  resource_id  VARCHAR(64)     NOT NULL,
  amount       INT UNSIGNED    NOT NULL,
  item_type    ENUM('Product','Substance','Technology') NOT NULL DEFAULT 'Substance',
  PRIMARY KEY (item_id),
  KEY (snapshot_id),
  CONSTRAINT fk_snapshot FOREIGN KEY (snapshot_id) REFERENCES nms_snapshots(snapshot_id) ON DELETE CASCADE,
  UNIQUE KEY uniq_slot (snapshot_id, owner_type, inventory, container_id, slot_index)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE OR REPLACE VIEW nms_items_norm AS
SELECT item_id, snapshot_id, owner_type, inventory, container_id, slot_index,
       REPLACE(resource_id,'^','') AS resource_id, amount, item_type
FROM nms_items;
"

echo "Database '$NMS_DB_NAME' reset and schema created."
