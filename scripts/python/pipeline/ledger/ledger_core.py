# scripts/python/pipeline/ledger/ledger_core.py
from typing import Any, Dict, Iterable, List, Tuple, Optional

def diff_inventories(a: Dict[Tuple[str, str], int], b: Dict[Tuple[str, str], int]) -> Dict[Tuple[str, str], int]:
    """Return b - a for each key in either map."""
    keys = set(a.keys()) | set(b.keys())
    return {k: b.get(k, 0) - a.get(k, 0) for k in keys}

def coalesce_sessions(rows: Iterable[Dict[str, Any]], max_gap_sec: int = 900) -> List[List[Dict[str, Any]]]:
    """Group chronological rows into sessions if adjacent timestamps are close."""
    out: List[List[Dict[str, Any]]] = []
    prev = None
    for r in sorted(rows, key=lambda x: x["ts"]):
        if not out:
            out.append([r]); prev = r; continue
        gap = (r["ts"] - prev["ts"]).total_seconds()
        if gap <= max_gap_sec:
            out[-1].append(r)
        else:
            out.append([r])
        prev = r
    return out

def write_ledger_to_db(rows: List[Dict[str, Any]], env_path, table: str, verbose: bool = False) -> None:
    """Insert ledger rows into MariaDB."""
    from .db_conn import _db_connect_from_env
    import datetime as dt
    conn = _db_connect_from_env(env_path)
    try:
        cur = conn.cursor()
        sql = f"INSERT INTO {table}(ts, owner_type, item_id, delta) VALUES (%s,%s,%s,%s)"
        for r in rows:
            cur.execute(sql, (r["ts"], r["owner_type"], r["item_id"], r["delta"]))
        conn.commit()
    finally:
        conn.close()
