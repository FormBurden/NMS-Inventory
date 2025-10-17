# scripts/python/pipeline/ledger/baseline_loader.py
from pathlib import Path
from typing import Any, Dict, Optional
from .db_conn import _db_connect_from_env, _manifest_source_mtime_safe

def load_baseline_from_db(table: str, env_path: Path) -> Dict:
    """Return a baseline inventory map from DB, keyed by (owner_type,item_id)."""
    conn = _db_connect_from_env(env_path)
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT owner_type,item_id,amount FROM {table}")
        out = {}
        for owner, item, amt in cur:
            out[(owner, item)] = int(amt)
        return out
    finally:
        conn.close()
