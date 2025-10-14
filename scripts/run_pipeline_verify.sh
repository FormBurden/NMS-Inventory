#!/usr/bin/env bash
# scripts/run_pipeline_verify.sh
# Wrapper to run your existing pipeline with xtrace, capture the printed decode
# destination, and VERIFY the file actually exists & is non-empty.

set -Eeuo pipefail

ROOT_DIR="${ROOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$ROOT_DIR"

mkdir -p .cache

TRACE_FILE=".cache/trace.run_pipeline.log"
DECODE_PRINT_RX='^\[PIPE\][[:space:]]+decoding[[:space:]]*->[[:space:]]*(.*\.json)[[:space:]]*$'

echo "[verify] running pipeline with xtrace..."
# shellcheck disable=SC2086
( set -x; bash scripts/run_pipeline.sh ) 2>&1 | tee "$TRACE_FILE"

echo "[verify] pipeline finished. analyzing: $TRACE_FILE"

# Extract the last printed decode target path from the trace/pipeline output.
DECODE_TARGET="$(
  { grep -E "$DECODE_PRINT_RX" "$TRACE_FILE" || true; } \
  | tail -n1 \
  | sed -E "s/$DECODE_PRINT_RX/\1/"
)"

if [[ -z "${DECODE_TARGET:-}" ]]; then
  echo "[verify][ERROR] Pipeline did not print a decode target line like:"
  echo "                [PIPE] decoding -> storage/decoded/save_YYYY-MM-DD_HH-MM-SS.json"
  echo "        See the full trace: $TRACE_FILE"
  exit 2
fi

# Normalize to absolute path for clarity
if [[ "${DECODE_TARGET}" != /* ]]; then
  DECODE_ABS="$ROOT_DIR/${DECODE_TARGET}"
else
  DECODE_ABS="${DECODE_TARGET}"
fi

echo "[verify] decode target (from pipeline): ${DECODE_TARGET}"
echo "[verify] absolute path:                 ${DECODE_ABS}"

# Verify file was actually created and non-empty
if [[ ! -s "${DECODE_ABS}" ]]; then
  echo "[verify][ERROR] The pipeline printed a decode target that does not exist or is empty:"
  echo "                ${DECODE_ABS}"
  echo
  echo "[verify] Recent contents of storage/decoded (most recent first):"
  ls -lat storage/decoded | sed '1,2!b' || true
  echo
  echo "[verify] Decoder calls seen in trace (python/nms_hg_decoder):"
  grep -nE 'python|nms_hg_decoder|decode' "$TRACE_FILE" || true
  echo
  echo "[verify] HINTS:"
  echo "  - The decoder may have failed but the pipeline printed the path anyway."
  echo "  - The decoder may be writing to a different location than what is printed."
  echo "  - The pipeline may be printing the path *before* running the decoder."
  exit 3
fi

echo "[verify] OK: decode file exists and is non-empty."
echo "          ${DECODE_ABS}"

# Optional: continue to the rest of your pipeline if you want
# (Uncomment if you eventually split stages; for now we just verify the decode step)
# echo "[verify] proceeding to import/fullparse stages..."
# bash scripts/import_latest.sh
exit 0

