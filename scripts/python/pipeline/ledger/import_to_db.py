# scripts/python/pipeline/ledger/import_to_db.py
from pathlib import Path
from typing import Any, Dict, Optional
from .db_conn import _db_connect_from_env

def initial_import_to_db(json_path, table: str, env_path: Path, use_mtime=False, include_tech=False, verbose=False) -> None:
    import json
    from .initial_import import _collect_initial_rows
    from .ts_utils import canonical_ts_from_file
    js = json.loads(Path(json_path).read_text(encoding="utf-8"))
    rows = _collect_initial_rows(js, include_tech=include_tech)
    ts = canonical_ts_from_file(json_path, use_mtime=use_mtime)

    conn = _db_connect_from_env(env_path)
    try:
        cur = conn.cursor()
        sql = f"INSERT INTO {table}(ts, owner_type, item_id, amount) VALUES (%s,%s,%s,%s)"
        for owner_type, item_id, amt in rows:
            cur.execute(sql, (ts, owner_type, item_id, int(amt)))
        conn.commit()
    finally:
        conn.close()
