#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

msg="${1:-update}"

git add .
git commit -m "$msg" || echo "Nothing to commit."
git push -u origin main