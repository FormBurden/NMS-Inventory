#!/usr/bin/env bash
# Build a single plain-text pack that inlines the contents of all files listed
# in .nmsinventory-files.txt (or a given --from manifest). Upload that ONE file.

set -Eeuo pipefail

FROM=".nmsinventory-files.txt"
OUT=".cache/assistant_pack.txt"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from) FROM="$2"; shift 2 ;;
    --out)  OUT="$2";  shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ ! -f "$FROM" ]]; then
  echo "Manifest not found: $FROM" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUT")"
: > "$OUT"

ROOT_DIR="${ROOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$ROOT_DIR"

echo "# assistant pack" >> "$OUT"
echo "# generated: $(date -Iseconds)" >> "$OUT"
echo "# manifest:  $FROM" >> "$OUT"
echo >> "$OUT"

i=0
while IFS= read -r rel; do
  [[ -z "$rel" ]] && continue
  [[ "$rel" =~ ^[[:space:]]*# ]] && continue
  i=$((i+1))
  path="$rel"
  if [[ ! -e "$path" ]]; then
    {
      echo "===== BEGIN FILE: $path ====="
      echo "STATUS: MISSING"
      echo "===== END FILE: $path ====="
      echo
    } >> "$OUT"
    continue
  fi
  sha="$(sha256sum "$path" | awk '{print $1}')"
  size="$(wc -c < "$path" | tr -d ' ')"
  echo "[$i] $path ($size bytes)" >&2
  {
    echo "===== BEGIN FILE: $path ====="
    echo "SHA256: $sha"
    echo "SIZE:   $size"
    echo
    cat "$path"
    echo
    echo "===== END FILE: $path ====="
    echo
  } >> "$OUT"
done < "$FROM"

echo "[ok] wrote $OUT" >&2
