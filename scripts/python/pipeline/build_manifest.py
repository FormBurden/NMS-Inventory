#!/usr/bin/env python3
import argparse, json, os, sys, hashlib
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
    """Pick most-recent decoded save (*.json) and its fullparse partner (<stem>.full.json)."""
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

def _derive_save_root_from_source_path(src: Path) -> str:
    """
    Best-effort: if decoded path contains something like .../NMS/<st_...>/save2.json,
    return that <st_...>. Otherwise return empty string (pipeline can set active root later).
    """
    for seg in src.parts[::-1]:
        if seg.startswith("st_"):
            return seg
    return ""

def main() -> int:
    ap = argparse.ArgumentParser(description="Build manifest for initial import")
    ap.add_argument("--source", default="", help="Original HG path (optional)")
    ap.add_argument("--source-mtime", default="", help="Source mtime (seconds) for provenance (optional)")
    args = ap.parse_args()

    pair = _latest_pair()
    if not pair:
        # Ensure no stale tmp remains; create an empty manifest atomically
        MANIFEST_TMP.write_text(json.dumps({"items": [], "snapshot_ts": None}) + "\n", encoding="utf-8")
        os.replace(MANIFEST_TMP, MANIFEST_FINAL)
        return 0

    decoded_path, out_json = pair
    src_mtime = decoded_path.stat().st_mtime
    out_mtime = out_json.stat().st_mtime if out_json.exists() else None

    # Hashes; importer expects 'json_sha256' representing the JSON we will load (out_json).
    out_sha = _sha256(out_json)
    src_sha = _sha256(decoded_path)

    # Derive save_root from decoded path if possible
    save_root = _derive_save_root_from_source_path(decoded_path)

    manifest = {
        "snapshot_ts": _iso_utc(src_mtime),
        "items": [
            {
                "source_path": str(decoded_path),            # path we decoded to
                "out_json":    str(out_json),                # fullparse JSON
                "save_root":   save_root,                    # helps UI grouping
                "source_mtime": _iso_utc(src_mtime),         # importer reads this
                "decoded_mtime": _iso_utc(out_mtime) if out_mtime else None,  # importer expects this key
                "json_sha256":  out_sha or "",               # importer expects this key
                # keep the originals too (harmless):
                "source_sha256": src_sha or "",
            }
        ],
    }

    # Atomic write
    MANIFEST_TMP.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(MANIFEST_TMP, MANIFEST_FINAL)
    return 0

if __name__ == "__main__":
    sys.exit(main())
