#!/usr/bin/env bash
# Rebuild the DB by applying schema_reset (if present) and all migrations in order.
# Prompts ONCE for the MariaDB password, then reuses it for every command.

set -Eeuo pipefail

# --- Resolve repo root (directory containing this script assumed to be scripts/) ---
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"

# --- Load environment (resolve ${NMS_DB_*} indirection if used) ---
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

# Prefer DB_* if set, else fall back to NMS_DB_*, else defaults
DB_USER="${DB_USER:-${NMS_DB_USER:-nms_user}}"
DB_NAME="${DB_NAME:-${NMS_DB_NAME:-nms_database}}"
DB_PASS="${DB_PASS:-${NMS_DB_PASS:-}}"

# Choose your default charset/collation (matches project)
DB_CHARSET="${DB_CHARSET:-utf8mb4}"
DB_COLLATE="${DB_COLLATE:-utf8mb4_unicode_ci}"

MIG_DIR="db/migrations"
if [[ ! -d "$MIG_DIR" ]]; then
  echo "[ERR] Missing migrations directory: $MIG_DIR" >&2
  exit 1
fi
# Track results for summary
MIG_OK=()
MIG_FAIL=()


# --- Prompt once for password; create a temporary defaults file ---
if [[ -z "${DB_PASS}" ]]; then
  read -rs -p "Enter MariaDB password for user '${DB_USER}': " DB_PASS
  echo
fi

CRED_FILE="$(mktemp -t nms-maria-XXXXXX.cnf)"
cleanup() {
  if command -v shred >/dev/null 2>&1; then
    shred -u "$CRED_FILE" || rm -f "$CRED_FILE"
  else
    rm -f "$CRED_FILE"
  fi
}
trap cleanup EXIT

cat >"$CRED_FILE" <<EOF
[client]
user=${DB_USER}
password=${DB_PASS}
EOF
chmod 600 "$CRED_FILE"

# --- Helpers ---
run_sql_global() {
  local sql="$1"
  mariadb --defaults-extra-file="$CRED_FILE" -N -e "$sql"
}

run_sql_db_file() {
  local sql_file="$1"
  if [[ ! -f "$sql_file" ]]; then
    echo "[WARN] SQL file not found: $sql_file" >&2
    return 0
  fi
  echo "[DB] Applying: ${sql_file}"
  if mariadb --defaults-extra-file="$CRED_FILE" -D "$DB_NAME" -N -e "SOURCE ${sql_file}"; then
    MIG_OK+=("$sql_file")
  else
    MIG_FAIL+=("$sql_file")
    return 1
  fi
}


run_sql_db() {
  local stmt="$1"
  mariadb --defaults-extra-file="$CRED_FILE" -D "$DB_NAME" -N -e "$stmt"
}

ensure_db_exists() {
  echo "[DB] Ensuring database exists: ${DB_NAME} (${DB_CHARSET} / ${DB_COLLATE})"
  run_sql_global "CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET ${DB_CHARSET} COLLATE ${DB_COLLATE};"
}

echo "[DB] Rebuild starting for database: ${DB_NAME} (user: ${DB_USER})"
echo "[DB] Migrations dir: ${MIG_DIR}"

# 0) Ensure DB exists BEFORE running schema_reset (so it can DROP/CREATE inside it)
ensure_db_exists

# 1) schema_reset.sql (run WITH -D so DROP VIEW/TABLE etc. have a selected DB)
if [[ -f "${MIG_DIR}/schema_reset.sql" ]]; then
  echo "[DB] Applying (db-scoped): ${MIG_DIR}/schema_reset.sql"
  run_sql_db_file "${MIG_DIR}/schema_reset.sql"
fi

# 2) Apply all other migrations in lexical order (with -D "${DB_NAME}")
# Collect migrations in lexical order, EXCLUDING schema_reset.sql (already applied above)
mapfile -t SQLS < <(ls -1 "${MIG_DIR}"/*.sql 2>/dev/null | sort | grep -v -E '/schema_reset\.sql$')
if [[ ${#SQLS[@]} -eq 0 ]]; then
  echo "[WARN] No *.sql migrations found in ${MIG_DIR}"
else
  for f in "${SQLS[@]}"; do
    run_sql_db_file "$f"
  done
fi


# 3) Quick sanity readouts (tolerate failures)
echo "[DB] Rebuild complete. Listing views and tables:"
run_sql_db "SHOW FULL TABLES WHERE Table_type IN ('VIEW','BASE TABLE');" || true

# 4) Summary
echo
echo "[DB] Migration summary:"
if (( ${#MIG_OK[@]} > 0 )); then
  echo "  [OK] ${#MIG_OK[@]} file(s):"
  for f in "${MIG_OK[@]}"; do
    echo "    • $f"
  done
else
  echo "  [OK] 0 file(s)"
fi

if (( ${#MIG_FAIL[@]} > 0 )); then
  echo "  [FAIL] ${#MIG_FAIL[@]} file(s):"
  for f in "${MIG_FAIL[@]}"; do
    echo "    • $f"
  done
  echo "[ERR] One or more migrations failed."
  exit 1
fi

echo "[OK] Done."
