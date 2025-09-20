#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

: "${NMSSAVETOOL:=$(grep '^NMSSAVETOOL=' .env 2>/dev/null | cut -d= -f2-)}"
: "${NMS_HG_PATH:=$(grep '^NMS_HG_PATH=' .env 2>/dev/null | cut -d= -f2-)}"
: "${SESSION_MINUTES:=$(grep '^SESSION_MINUTES=' .env 2>/dev/null | cut -d= -f2-)}"
: "${USE_MTIME:=$(grep '^USE_MTIME=' .env 2>/dev/null | cut -d= -f2-)}"
: "${INITIAL_TABLE:=$(grep '^INITIAL_TABLE=' .env 2>/dev/null | cut -d= -f2-)}"
: "${LEDGER_TABLE:=$(grep '^LEDGER_TABLE=' .env 2>/dev/null | cut -d= -f2-)}"

DEC="$ROOT/storage/decoded"
CLEAN="$ROOT/storage/cleaned"
LOGS="$ROOT/storage/logs"

stamp="$(date +'%Y-%m-%d_%H-%M-%S')"
raw_json="$DEC/save_$stamp.json"
clean_json="$CLEAN/save_$stamp.cleaned.json"

echo "[PIPE] decoding -> $raw_json"
python3 "$NMSSAVETOOL" decompress "$NMS_HG_PATH" "$raw_json" >"$LOGS/nmssavetool.$stamp.log" 2>&1

echo "[PIPE] cleaning -> $clean_json"
python3 /mnt/data/nms_decode_clean.py --json "$raw_json" --out "$clean_json" \
  --print-summary >"$LOGS/nms_decode_clean.$stamp.log" 2>&1

# Initial import (stores a full baseline snapshot rowset)
echo "[PIPE] initial import into DB ($INITIAL_TABLE)"
python3 /mnt/data/nms_resource_ledger_v3.py --initial \
  --saves "$clean_json" \
  --db-import --db-env "$ROOT/.env" --db-table "$INITIAL_TABLE" \
  --use-mtime >"$LOGS/initial_import.$stamp.log" 2>&1

# Ledger: compare current JSON vs baseline in DB (latest snapshot)
# Writes session deltas into LEDGER_TABLE
echo "[PIPE] ledger compare (baseline=latest) -> $LEDGER_TABLE"
python3 /mnt/data/nms_resource_ledger_v3.py \
  --saves "$CLEAN" \
  --baseline-db-table "$INITIAL_TABLE" \
  --baseline-snapshot latest \
  --db-write-ledger --db-env "$ROOT/.env" --db-ledger-table "$LEDGER_TABLE" \
  --session-minutes "${SESSION_MINUTES:-15}" \
  ${USE_MTIME:+--use-mtime} >"$LOGS/ledger.$stamp.log" 2>&1

echo "[PIPE] done."
