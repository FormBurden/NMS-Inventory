# scripts/python/pipeline/ledger/io_utils.py
from pathlib import Path
from typing import Dict

def pick_latest_json_from_path(path: Path, use_mtime=False) -> Dict[str, Path]:
    best = None
    for p in path.glob("*.json"):
        ts = p.stat().st_mtime if use_mtime else p.stat().st_mtime
        if best is None or ts > best[0]:
            best = (ts, p)
    if not best:
        raise FileNotFoundError(f"No *.json under {path}")
    return {"path": best[1], "mtime": best[0]}
