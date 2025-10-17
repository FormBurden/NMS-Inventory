# scripts/python/pipeline/ledger/initial_import.py
from typing import Any, Dict, Iterable, List, Tuple, Optional
import csv
import re

def _escape_sql(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")

def _collect_initial_rows(js: Dict[str, Any], include_tech: bool = False) -> List[Tuple[str, str, int]]:
    from .inventory import aggregate_inventory
    totals = aggregate_inventory(js, include_tech=include_tech)
    rows: List[Tuple[str, str, int]] = []
    for (owner_type, item_id), amt in sorted(totals.items()):
        rows.append((owner_type, item_id, int(amt)))
    return rows

def initial_import_to_csv_sql(json_path, out_csv, out_sql, use_mtime=False, include_tech=False, verbose=False) -> None:
    import json
    from pathlib import Path
    from .ts_utils import canonical_ts_from_file
    js = json.loads(Path(json_path).read_text(encoding="utf-8"))
    rows = _collect_initial_rows(js, include_tech=include_tech)
    ts = canonical_ts_from_file(json_path, use_mtime=use_mtime)

    # CSV
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts","owner_type","item_id","amount"])
        for owner_type, item_id, amt in rows:
            w.writerow([ts.isoformat(), owner_type, item_id, amt])

    # SQL
    values_sql = []
    for owner_type, item_id, amt in rows:
        values_sql.append(
            f"('{_escape_sql(ts.isoformat())}','{_escape_sql(owner_type)}','{_escape_sql(item_id)}',{int(amt)})"
        )
    out_sql.write_text("INSERT INTO initial_items(ts,owner_type,item_id,amount) VALUES\n" + ",\n".join(values_sql) + ";\n", encoding="utf-8")

def _split_sql_values_row(line: str) -> List[str]:
    acc = []; cur = []; esc = False
    for ch in line:
        if esc:
            cur.append(ch); esc = False; continue
        if ch == "\\":
            esc = True; cur.append(ch); continue
        if ch == ",":
            acc.append("".join(cur).strip()); cur = []; continue
        cur.append(ch)
    if cur:
        acc.append("".join(cur).strip())
    return acc

def parse_initial_sql_totals(sql_text: str) -> Dict[Tuple[str,str], int]:
    # Very tolerant parser for VALUES rows like:  ('2025-10-16', 'character','DI_HYDROGEN', 42)
    totals: Dict[Tuple[str,str], int] = {}
    for line in sql_text.splitlines():
        if not line.strip().startswith("("):
            continue
        cols = _split_sql_values_row(line.strip().strip(",").strip("()"))
        if len(cols) != 4:
            continue
        _, owner_q, item_q, amt = cols
        owner = owner_q.strip().strip("'")
        item = item_q.strip().strip("'")
        totals[(owner,item)] = totals.get((owner,item), 0) + int(amt)
    return totals
