#!/usr/bin/env python3
import json
import os
import sys
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Tuple

# Project root: scripts/python/pipeline/ -> project root
ROOT = Path(__file__).resolve().parents[3]
DECODED_DIR = ROOT / "storage" / "decoded"
FULLPARSE_DIR = ROOT / "output" / "fullparse"
MANIFEST_FINAL = DECODED_DIR / "_manifest_recent.json"
MANIFEST_TMP = DECODED_DIR / "_manifest_recent.json.tmp"

def _iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(microsecond=0).isoformat()

def _sha256(p: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except FileNotFoundError:
        return None

def _latest_pair() -> Optional[Tuple[Path, Path]]:
    """
    Heuristic: pick the most recently modified decoded save (*.json) and match its
    fullparse partner (same stem, '.full.json' under output/fullparse).
    """
    if not DECODED_DIR.exists():
        return None
    candidates = sorted(
        (p for p in DECODED_DIR.glob("*.json") if p.name != "_manifest_recent.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for src in candidates:
        stem = src.stem  # e.g., "save" or "save2"
        out = FULLPARSE_DIR / f"{stem}.full.json"
        if out.exists():
            return (src, out)
    return None

def main() -> int:
    pair = _latest_pair()
    if not pair:
        # Ensure no stale tmp remains; create an empty manifest atomically
        MANIFEST_TMP.write_text(json.dumps({"items": [], "snapshot_ts": None}) + "\n", encoding="utf-8")
        os.replace(MANIFEST_TMP, MANIFEST_FINAL)
        return 0

    source_path, out_json = pair
    # File metadata
    src_mtime = source_path.stat().st_mtime
    out_mtime = out_json.stat().st_mtime if out_json.exists() else None
    src_sha = _sha256(source_path)
    out_sha = _sha256(out_json) if out_json.exists() else None

    # Define snapshot_ts from decoded file mtime (decode completion time)
    snapshot_ts = _iso_utc(src_mtime)

    manifest = {
        "snapshot_ts": snapshot_ts,
        "items": [
            {
                "source_path": str(source_path),
                "out_json": str(out_json),
                "source_mtime": _iso_utc(src_mtime),
                "out_mtime": _iso_utc(out_mtime) if out_mtime else None,
                "source_sha256": src_sha,
                "out_sha256": out_sha,
            }
        ],
    }

    # Atomic write: write .tmp then replace
    MANIFEST_TMP.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(MANIFEST_TMP, MANIFEST_FINAL)
    return 0

if __name__ == "__main__":
    sys.exit(main())
