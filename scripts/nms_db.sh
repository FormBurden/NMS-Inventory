#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
case "${1:-}" in
  --initial)  "$REPO_ROOT/scripts/import_latest.sh" ;;
  --reset)    "$REPO_ROOT/scripts/db_reset.sh" ;;
  *) echo "Usage: $0 --initial | --reset"; exit 1;;
esac
