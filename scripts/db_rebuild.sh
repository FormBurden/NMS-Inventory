#!/usr/bin/env bash
# Rebuild the DB by applying schema_reset (if present) and all migrations in order.
# Prompts for MariaDB password ONLY if not provided via DB_PASS or NMS_DB_PASS.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT"

ENV_FILE="${ENV_FILE:-$ROOT/.env}"
[[ -f "$ENV_FILE" ]] || { echo "[db_rebuild] Missing .env at $ENV_FILE"; exit 2; }

set -a; source "$ENV_FILE"; set +a
: "${NMS_DB_USER:?}"
: "${NMS_DB_NAME:?}"

# Password reuse (from db_reset.sh) or .env; prompt only if still empty
if [[ -z "${DB_PASS:-}" ]]; then
  if [[ -n "${NMS_DB_PASS:-}" ]]; then
    DB_PASS="$NMS_DB_PASS"
  else
    read -rsp "Enter password: " DB_PASS; echo
  fi
fi
export DB_PASS

MIG_DIR="$ROOT/db/migrations"

echo "[DB] Rebuild starting for database: $NMS_DB_NAME (user: $NMS_DB_USER)"
echo "[DB] Migrations dir: $MIG_DIR"

# Wrapper to ensure the preferred flags and one-time password usage
maria() { mariadb -u "$NMS_DB_USER" -p"$DB_PASS" "$@"; }

# Helper: execute an inline SQL string against the target DB
dbq() { local sql="$1"; maria -D "$NMS_DB_NAME" -N -e "$sql"; }

# Ensure the database exists (omit -D by definition here)
maria -N -e "CREATE DATABASE IF NOT EXISTS \`$NMS_DB_NAME\` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# Apply a migration file (cat -> -e). Assumes no DELIMITER changes in files.
apply_file() {
  local f="$1"
  [[ -f "$f" ]] || { echo "[DB][SKIP] Missing $f"; return 0; }
  echo "[DB] Applying: $f"
  local sql; sql="$(cat "$f")"
  maria -D "$NMS_DB_NAME" -N -e "$sql"
}

# 1) Apply schema_reset.sql first if present (db-scoped echo retained)
if [[ -f "$MIG_DIR/schema_reset.sql" ]]; then
  echo "[DB] Applying (db-scoped): $MIG_DIR/schema_reset.sql"
  apply_file "$MIG_DIR/schema_reset.sql"
fi

# 2) Apply all numbered migrations in ascending order; preserves 0014 before 0015
shopt -s nullglob
mapfile -t MIGS < <(ls -1 "$MIG_DIR"/20*.sql | sort)
for f in "${MIGS[@]}"; do
  base="$(basename "$f")"
  [[ "$base" == "schema_reset.sql" ]] && continue
  apply_file "$f"
done

echo "[DB] Rebuild complete."
