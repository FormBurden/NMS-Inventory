#!/usr/bin/env bash
# scripts/db_diag.sh
# Single-file MariaDB diagnostics report for NMS-Inventory.
# Writes one consolidated text file with all checks and graceful fallbacks.
#
# Output: output/diag/YYYYMMDD-HHMMSS/db_diagnostics.txt

set -euo pipefail

# ---------- Config ----------
DB_NAME="nms_database"
DB_USER="nms_user"

read -r -s -p "Enter password: " DB_PASS
echo

STAMP="$(date +%Y%m%d-%H%M%S)"
OUTDIR="output/diag/${STAMP}"
OUTTXT="${OUTDIR}/db_diagnostics.txt"
mkdir -p "${OUTDIR}"

# MariaDB base (respect project rule; reuse single password)
MDB=(mariadb -u "${DB_USER}" -p"${DB_PASS}" -D "${DB_NAME}" -N -e)

say() { printf "[diag] %s\n" "$*" >&2; }
hr() { printf -- "========================================================================\n"; }
sec() { printf "\n"; hr; printf "== %s\n" "$*"; hr; }

# Run SQL and append to OUTTXT with header.
# sql_section "Title" "header\tcols" "SQL..."
sql_section() {
  local title="$1"; shift
  local header="$1"; shift
  local q="$1"; shift || true

  {
    sec "${title}"
    printf "%s\n" "${header}"
    "${MDB[@]}" "${q}" 2>&1 || true
  } >> "${OUTTXT}"
}

# Run SHOW/DDL and append to OUTTXT.
# ddl_section "Title" "SQL..."
ddl_section() {
  local title="$1"; shift
  local q="$1"; shift || true
  {
    sec "${title}"
    "${MDB[@]}" "${q}" 2>&1 || true
  } >> "${OUTTXT}"
}

# existence helpers
has_base_table() {
  local tbl="$1"
  "${MDB[@]}" "SHOW FULL TABLES WHERE Table_type='BASE TABLE' AND Tables_in_${DB_NAME}='${tbl}';" | grep -q .
}
has_view() {
  local vw="$1"
  "${MDB[@]}" "SHOW FULL TABLES WHERE Table_type='VIEW' AND Tables_in_${DB_NAME}='${vw}';" | grep -q .
}
has_column() {
  local tbl="$1" col="$2"
  "${MDB[@]}" "SELECT 1 FROM information_schema.COLUMNS
                WHERE table_schema='${DB_NAME}' AND table_name='${tbl}'
                  AND column_name='${col}' LIMIT 1;" | grep -q 1
}

say "Output: ${OUTTXT}"

# ---------- Sections ----------

# 1) Schema collation
sql_section "Schema collation" \
  "schema_name\tdefault_collation_name" \
  "SELECT schema_name, default_collation_name
     FROM information_schema.SCHEMATA
    WHERE schema_name='${DB_NAME}';"

# 2) Base tables presence
sql_section "Base tables present (snapshots/items/resources)" \
  "table_name\ttable_type" \
  "SHOW FULL TABLES WHERE Table_type='BASE TABLE'
     AND Tables_in_${DB_NAME} IN ('nms_snapshots','nms_items','nms_resources');"

# 3) API views presence
sql_section "API views present (v_api_inventory_rows*)" \
  "table_name\ttable_type" \
  "SHOW FULL TABLES WHERE Table_type='VIEW'
     AND Tables_in_${DB_NAME} LIKE 'v_api_inventory_rows%';"

# 4) Row counts
if has_base_table "nms_snapshots" && has_base_table "nms_items"; then
  if has_base_table "nms_resources"; then
    sql_section "Row counts (snapshots/items/resources)" \
      "snapshots\titems\tresources" \
      "SELECT (SELECT COUNT(*) FROM nms_snapshots) AS snapshots,
              (SELECT COUNT(*) FROM nms_items)     AS items,
              (SELECT COUNT(*) FROM nms_resources) AS resources;"
  else
    sql_section "Row counts (snapshots/items; resources missing)" \
      "snapshots\titems\tresources" \
      "SELECT (SELECT COUNT(*) FROM nms_snapshots) AS snapshots,
              (SELECT COUNT(*) FROM nms_items)     AS items,
              NULL AS resources;"
  fi
else
  {
    sec "Row counts (tables missing)"
    printf "snapshots\titems\tresources\nN/A\tN/A\tN/A\n"
  } >> "${OUTTXT}"
fi

# 5) Latest snapshots (top 5) — use snapshot_id DESC (no created_at dep)
if has_base_table "nms_snapshots"; then
  sql_section "Latest snapshots (top 5 by snapshot_id)" \
    "snapshot_id\tsave_root" \
    "SELECT snapshot_id, save_root
       FROM nms_snapshots
   ORDER BY snapshot_id DESC
      LIMIT 5;"
else
  {
    sec "Latest snapshots (nms_snapshots missing)"
    printf "snapshot_id\tsave_root\nN/A\tN/A\n"
  } >> "${OUTTXT}"
fi

# 6) Items by owner_type/inventory for newest snapshot (MAX snapshot_id)
if has_base_table "nms_items" && has_base_table "nms_snapshots"; then
  sql_section "Items by owner_type/inventory for newest snapshot" \
    "owner_type\tinventory\tn_rows\ttotal_amount" \
    "SELECT i.owner_type, i.inventory,
            COUNT(*) AS n_rows, COALESCE(SUM(i.amount),0) AS total_amount
       FROM nms_items i
      WHERE i.snapshot_id=(SELECT MAX(snapshot_id) FROM nms_snapshots)
   GROUP BY 1,2
   ORDER BY 1,2;"
else
  {
    sec "Items by owner_type/inventory (tables missing)"
    printf "owner_type\tinventory\tn_rows\ttotal_amount\nN/A\tN/A\t0\t0\n"
  } >> "${OUTTXT}"
fi

# 7) Orphan items
if has_base_table "nms_items" && has_base_table "nms_snapshots"; then
  sql_section "Orphan items (no parent snapshot)" \
    "orphan_items" \
    "SELECT COUNT(*) AS orphan_items
       FROM nms_items i
  LEFT JOIN nms_snapshots s ON s.snapshot_id=i.snapshot_id
      WHERE s.snapshot_id IS NULL;"
else
  {
    sec "Orphan items (tables missing)"
    printf "orphan_items\nN/A\n"
  } >> "${OUTTXT}"
fi

# 8) Missing resource entries (count)
if has_base_table "nms_items" && has_base_table "nms_resources"; then
  sql_section "Missing resource entries used by items (count)" \
    "missing_resources" \
    "SELECT COUNT(DISTINCT i.resource_id) AS missing_resources
       FROM nms_items i
  LEFT JOIN nms_resources r ON r.resource_id=i.resource_id
      WHERE r.resource_id IS NULL;"
else
  {
    sec "Missing resource entries (nms_resources missing)"
    printf "missing_resources\nN/A\n"
  } >> "${OUTTXT}"
fi

# 9) Missing resource_ids (sample 10)
if has_base_table "nms_items" && has_base_table "nms_resources"; then
  sql_section "Sample missing resource_ids (first 10)" \
    "resource_id" \
    "SELECT DISTINCT i.resource_id
       FROM nms_items i
  LEFT JOIN nms_resources r ON r.resource_id=i.resource_id
      WHERE r.resource_id IS NULL
      LIMIT 10;"
else
  {
    sec "Sample missing resource_ids (nms_resources missing)"
    printf "resource_id\nN/A\n"
  } >> "${OUTTXT}"
fi

# 10) Column collation checks
sql_section "Column collations (save_root/resource_id)" \
  "table_name\tcolumn_name\tcollation_name" \
  "SELECT table_name, column_name, collation_name
     FROM information_schema.COLUMNS
    WHERE table_schema='${DB_NAME}'
      AND table_name IN ('nms_save_roots','nms_items')
      AND column_name IN ('save_root','resource_id')
 ORDER BY table_name, column_name;"

# 11) Active view rowcount (if present)
if has_view "v_api_inventory_rows_active"; then
  sql_section "Active view rowcount" \
    "view\trowcount" \
    "SELECT 'v_api_inventory_rows_active' AS view_name, COUNT(*) AS rowcount
       FROM v_api_inventory_rows_active;"
else
  {
    sec "Active view rowcount"
    printf "view\trowcount\nv_api_inventory_rows_active\tN/A (view missing)\n"
  } >> "${OUTTXT}"
fi

# 12) Active view TOP 20 — adapt to available columns to avoid 'unknown column'
if has_view "v_api_inventory_rows_active"; then
  have_owner=$(has_column "v_api_inventory_rows_active" "owner_type" && echo 1 || echo 0)
  have_inventory=$(has_column "v_api_inventory_rows_active" "inventory" && echo 1 || echo 0)
  have_resources=$(has_base_table "nms_resources" && echo 1 || echo 0)

  if [ "$have_owner" -eq 1 ] && [ "$have_inventory" -eq 1 ]; then
    if [ "$have_resources" -eq 1 ]; then
      sql_section "Active view TOP 20 by amount (owner/inventory/resource with labels)" \
        "owner_type\tinventory\tresource_id\tlabel\tamount" \
        "SELECT a.owner_type, a.inventory, a.resource_id,
                COALESCE(r.display_name,r.name,r.code) AS label,
                SUM(a.amount) AS amount
           FROM v_api_inventory_rows_active a
      LEFT JOIN nms_resources r ON r.resource_id=a.resource_id
       GROUP BY 1,2,3,4
       ORDER BY amount DESC
          LIMIT 20;"
    else
      sql_section "Active view TOP 20 by amount (owner/inventory/resource; no labels)" \
        "owner_type\tinventory\tresource_id\tlabel\tamount" \
        "SELECT a.owner_type, a.inventory, a.resource_id,
                NULL AS label,
                SUM(a.amount) AS amount
           FROM v_api_inventory_rows_active a
       GROUP BY 1,2,3,4
       ORDER BY amount DESC
          LIMIT 20;"
    fi
  else
    # Fallback if the view doesn't expose owner_type/inventory
    if [ "$have_resources" -eq 1 ]; then
      sql_section "Active view TOP 20 by amount (resource-only with labels)" \
        "resource_id\tlabel\tamount" \
        "SELECT a.resource_id,
                COALESCE(r.display_name,r.name,r.code) AS label,
                SUM(a.amount) AS amount
           FROM v_api_inventory_rows_active a
      LEFT JOIN nms_resources r ON r.resource_id=a.resource_id
       GROUP BY 1,2
       ORDER BY amount DESC
          LIMIT 20;"
    else
      sql_section "Active view TOP 20 by amount (resource-only; no labels)" \
        "resource_id\tamount" \
        "SELECT a.resource_id,
                SUM(a.amount) AS amount
           FROM v_api_inventory_rows_active a
       GROUP BY 1
       ORDER BY amount DESC
          LIMIT 20;"
    fi
  fi
else
  {
    sec "Active view TOP 20"
    printf "N/A (v_api_inventory_rows_active missing)\n"
  } >> "${OUTTXT}"
fi

# 13) SHOW CREATE VIEWs (text)
if has_view "v_api_inventory_rows_by_root"; then
  ddl_section "SHOW CREATE VIEW v_api_inventory_rows_by_root" \
    "SHOW CREATE VIEW v_api_inventory_rows_by_root"
else
  {
    sec "SHOW CREATE VIEW v_api_inventory_rows_by_root"
    printf "(view missing)\n"
  } >> "${OUTTXT}"
fi

if has_view "v_api_inventory_rows_active"; then
  ddl_section "SHOW CREATE VIEW v_api_inventory_rows_active" \
    "SHOW CREATE VIEW v_api_inventory_rows_active"
else
  {
    sec "SHOW CREATE VIEW v_api_inventory_rows_active"
    printf "(view missing)\n"
  } >> "${OUTTXT}"
fi

# ---------- Summary ----------
say "Done. See ${OUTTXT}"
