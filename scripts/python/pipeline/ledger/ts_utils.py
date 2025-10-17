# scripts/python/pipeline/ledger/ts_utils.py
from typing import Any, Dict, List, Optional
import datetime as dt

# ---------------- Timestamp helpers ----------------
def parse_any_timestamp(js: Dict[str, Any]) -> Optional[dt.datetime]:
    candidates: List[str] = []
    for k in ("Timestamp", "SaveTime"):
        v = js.get(k)
        if isinstance(v, str):
            candidates.append(v)
    meta = js.get("Meta")
    if isinstance(meta, dict):
        for k in ("timestamp", "save_time", "created_at"):
            v = meta.get(k)
            if isinstance(v, str):
                candidates.append(v)
    for s in candidates:
        try:
            return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            pass
    return None

def canonical_ts_from_file(path: str, use_mtime: bool = False) -> dt.datetime:
    """Prefer in-file Timestamp/SaveTime; fallback to mtime when asked."""
    p = str(path)
    if not use_mtime:
        try:
            import json
            from pathlib import Path
            js = json.loads(Path(p).read_text(encoding="utf-8"))
            ts = parse_any_timestamp(js)  # type: ignore
            if ts:
                return ts
        except Exception:
            pass
    import os
    return dt.datetime.fromtimestamp(os.path.getmtime(p)).astimezone(dt.timezone.utc)
