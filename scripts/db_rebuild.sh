#!/usr/bin/env bash
# scripts/db_rebuild.sh
# Wipe-and-rebuild the NMS-Inventory MariaDB schema using project migrations only.
# Order: core (0009) -> resources (0010) -> views (0011) -> baseline (0012)

set -euo pipefail

# --- Config ---------------------------------------------------------------
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

# Allow overrides via environment. Defaults per your standard.
DB_USER="${DB_USER:-nms_user}"
DB_NAME="${DB_NAME:-nms_database}"

# Migrations (required)
MIG_CORE="$ROOT/db/migrations/20251016_0009_create_core_tables.sql"
MIG_RES="$ROOT/db/migrations/20251016_0010_create_nms_resources.sql"
MIG_VIEWS="$ROOT/db/migrations/20251016_0011_fix_views_owner_and_ledger.sql"
MIG_INIT="$ROOT/db/migrations/20251016_0012_create_initial_items.sql"

# --- Helpers --------------------------------------------------------------
die() { echo "[ERR] $*" >&2; exit 1; }

need_file() {
  local f="$1"
  [[ -f "$f" ]] || die "Missing required migration: $f"
}

sql() {
  # Usage: sql "MULTI-LINE SQL"
  local q="$1"
  echo "$q" | mariadb -u "$DB_USER" -p -D "$DB_NAME" -N -e "" || die "SQL failed"
}

source_sql() {
  local f="$1"
  need_file "$f"
  echo "[migrate] SOURCE $(basename "$f")"
  mariadb -u "$DB_USER" -p -D "$DB_NAME" -N -e "SOURCE $f" || die "SOURCE failed: $f"
}

show_schema() {
  echo "[info] Tables/Views after migrate:"
  mariadb -u "$DB_USER" -p -D "$DB_NAME" -N -e "SHOW FULL TABLES WHERE Table_type IN ('VIEW','BASE TABLE')"
}

usage() {
  cat <<USAGE
Usage: $(basename "$0") [--wipe|--no-wipe]

Options:
  --wipe     Drop project views and tables, then re-create schema (default)
  --no-wipe  Do NOT drop anything; just apply migrations in order

Env overrides:
  DB_USER (default: nms_user)
  DB_NAME (default: nms_database)

This script always prompts for the MariaDB password via -p (no password is echoed).
USAGE
}

# --- Args -----------------------------------------------------------------
DO_WIPE=1
if [[ "${1:-}" == "--no-wipe" ]]; then
  DO_WIPE=0
elif [[ "${1:-}" == "--wipe" ]] || [[ -z "${1:-}" ]]; then
  DO_WIPE=1
elif [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage; exit 0
else
  usage; die "Unknown option: $1"
fi

echo "[info] ROOT=$ROOT"
echo "[info] DB_USER=$DB_USER DB_NAME=$DB_NAME"
echo "[info] Mode: $([[ $DO_WIPE -eq 1 ]] && echo wipe || echo no-wipe)"

# Ensure migrations exist
need_file "$MIG_CORE"
need_file "$MIG_RES"
need_file "$MIG_VIEWS"
need_file "$MIG_INIT"

# --- Wipe (optional) ------------------------------------------------------
if [[ $DO_WIPE -eq 1 ]]; then
  echo "[wipe] Dropping views if they exist..."
  sql "DROP VIEW IF EXISTS
    v_api_inventory_rows_active,
    v_api_inventory_rows_active_combined,
    v_api_inventory_rows_by_root,
    v_latest_snapshot_by_root;"

  echo "[wipe] Dropping tables if they exist..."
  sql "SET FOREIGN_KEY_CHECKS=0;
       DROP TABLE IF EXISTS
         nms_ledger_deltas,
         nms_initial_items,
         nms_items,
         nms_resources,
         nms_snapshots,
         nms_save_roots,
         nms_settings;
       SET FOREIGN_KEY_CHECKS=1;"
fi

# --- Apply in correct order ----------------------------------------------
source_sql "$MIG_CORE"   # 0009 core tables
source_sql "$MIG_RES"    # 0010 resources (safe if empty)
source_sql "$MIG_VIEWS"  # 0011 views and owner/ledger deps
source_sql "$MIG_INIT"   # 0012 initial baseline table

show_schema
echo "[done] DB schema is ready."
