#!/usr/bin/env bash
set -Eeuo pipefail

# BEGIN CONTRACT
# FILETYPE: bash
# PURPOSE: Reset MariaDB database and re-apply all migrations (delegates to scripts/db_rebuild.sh).
# EXPORTS: (script entrypoint only)
# REQUIRES:
#   - binaries: mariadb
#   - files: .env at $ENV_FILE (default $ROOT/.env), scripts/db_rebuild.sh
#   - env: NMS_DB_USER (required), NMS_DB_NAME (required), NMS_DB_PASS (optional), ENV_FILE (optional)
# INVARIANTS:
#   - Drops & recreates `$NMS_DB_NAME` with utf8mb4/utf8mb4_unicode_ci.
#   - Prompts at most once for password; exports DB_PASS for child scripts.
#   - Uses MariaDB CLI: mariadb -u "$NMS_DB_USER" -p"$DB_PASS" -N -e "<DROP; CREATE>"
#   - Shell options: set -Eeuo pipefail
# SIDE EFFECTS:
#   - Exports DB_PASS to environment
#   - Destroys and recreates the target database
# LIMITS:
#   - ≤300 lines; do not mix shell+python.
# END CONTRACT


# NMS-Inventory: Reset database and re-apply all migrations
# - Prompts for MariaDB password ONCE and exports it for db_rebuild.sh reuse.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"

[[ -f "$ENV_FILE" ]] || { echo "[db_reset] Missing .env at $ENV_FILE"; exit 2; }

# Load env
set -a; source "$ENV_FILE"; set +a
: "${NMS_DB_USER:?}"
: "${NMS_DB_NAME:?}"

# Get password once (env wins if already present)
if [[ -z "${DB_PASS:-}" ]]; then
  if [[ -n "${NMS_DB_PASS:-}" ]]; then
    DB_PASS="$NMS_DB_PASS"
  else
    read -rsp "Enter password: " DB_PASS; echo
  fi
fi
export DB_PASS

echo "[DB] Reset starting for database: $NMS_DB_NAME (user: $NMS_DB_USER)"

# For DROP/CREATE, target DB may not exist; do not pass -D here.
mariadb -u "$NMS_DB_USER" -p"$DB_PASS" -N -e \
  "DROP DATABASE IF EXISTS \`$NMS_DB_NAME\`;
   CREATE DATABASE \`$NMS_DB_NAME\` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# Delegate to rebuild (reuses exported DB_PASS without prompting again)
exec "$ROOT/scripts/db_rebuild.sh"
