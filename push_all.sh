#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

msg="${1:-update}"
branch="$(git branch --show-current)"

if [[ -z "$branch" ]]; then
    echo "Unable to determine current Git branch."
    exit 1
fi

git rm -r --cached . >/dev/null
git add -A

if git diff --cached --quiet; then
    echo "Nothing to commit."
else
    git commit -m "$msg"
fi

git push -u origin "$branch"