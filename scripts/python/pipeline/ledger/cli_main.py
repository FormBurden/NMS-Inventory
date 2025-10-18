import argparse
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple, Optional, Union

# Package-import shim for direct execution
if __package__ in (None, ""):
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[5]))

# Leaf imports only (avoid aggregator __init__ which imports db_conn with redacted password literal)
from scripts.python.pipeline.ledger.initial_import import _escape_sql  # type: ignore
from scripts.python.pipeline.ledger.inventory import aggregate_inventory
from scripts.python.pipeline.ledger.ts_utils import canonical_ts_from_file

def _load_manifest(path: Path) -> Dict[str, Any]:
    import json
    return json.loads(path.read_text(encoding="utf-8"))

def _read_json(path: Path) -> Dict[str, Any]:
    import json
    return json.loads(path.read_text(encoding="utf-8"))

def _find_best_json(item: Dict[str, Any]) -> Optional[Path]:
    """
    Resolve the most useful JSON to aggregate, in order of preference:
      1) out_json (full-parse output) if present
      2) cleaned JSON derived from decoded path: /decoded/<name>.json -> /cleaned/<name>.clean.json
      3) source_path (decoded json) as a last resort
    """
    # Provided by manifest?
    out_json = item.get("out_json")
    if out_json:
        p = Path(out_json)
        if p.exists():
            return p

    # Try to derive cleaned path from decoded source_path
    source = item.get("source_path")
    if source:
        sp = Path(source)
        # /decoded/<name>.json -> /cleaned/<name>.clean.json
        try:
            parts = list(sp.parts)
            if "decoded" in parts:
                parts[parts.index("decoded")] = "cleaned"
                stem = sp.stem  # e.g., save2
                cleaned = Path(*parts[:-1]) / f"{stem}.clean.json"
                if cleaned.exists():
                    return cleaned
        except Exception:
            pass

    # Fallback: decoded json
    if source:
        sp = Path(source)
        if sp.exists():
            return sp

    return None

def _emit_initial_sql(json_path: Path, include_tech: bool = False, use_mtime: bool = False) -> str:
    js = _read_json(json_path)
    # Expect aggregate_inventory(js) -> Dict[(owner_type, inventory, resource_id), amount]
    totals = aggregate_inventory(js, include_tech=include_tech)
    if not totals:
        return "/* no snapshot rows generated */\n"

    ts = canonical_ts_from_file(json_path, use_mtime=use_mtime)
    ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")

    # Build SQL for nms_snapshots + nms_items (rows for latest snapshot)
    rows = []
    for (owner_type, inventory, resource_id), amt in sorted(totals.items()):
        rows.append(
            f"(@sid, '{_escape_sql(str(owner_type))}', "
            f"'{_escape_sql(str(inventory))}', "
            f"'{_escape_sql(str(resource_id))}', {int(amt)})"
        )
    values_blob = ",\n".join(rows)

    sql = []
    sql.append("START TRANSACTION;")
    sql.append(f"INSERT INTO nms_snapshots(snapshot_ts) VALUES ('{ts_str}');")
    sql.append("SET @sid := LAST_INSERT_ID();")
    sql.append("INSERT INTO nms_items(snapshot_id, owner_type, inventory, resource_id, amount) VALUES")
    sql.append(values_blob + ";")
    sql.append("COMMIT;")
    return "\n".join(sql) + "\n"

def main() -> None:
    import sys
    p = argparse.ArgumentParser(prog="nms-inventory-cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("initial_import", help="Generate baseline SQL for latest snapshot/items")
    p_init.add_argument("--manifest", required=True, type=Path)
    p_init.add_argument("--db-name", required=False)  # accepted but unused in SQL generation
    p_init.add_argument("--include-tech", action="store_true", default=False)
    p_init.add_argument("--use-mtime", action="store_true", default=False)
    args = p.parse_args()

    if args.cmd == "initial_import":
        manifest = _load_manifest(args.manifest)
        items = manifest.get("items") or []
        if not items:
            print("/* no snapshot rows generated */")
            return

        item0 = items[0]  # latest
        json_path = _find_best_json(item0)
        if not json_path or not json_path.exists():
            print("/* no snapshot rows generated */")
            print(f"[initial_import] No usable JSON found for item: {item0}", file=sys.stderr)
            return

        sql = _emit_initial_sql(json_path, include_tech=bool(args.include_tech), use_mtime=bool(args.use_mtime))
        # Helpful diagnostics go to stderr; SQL only to stdout
        try:
            js = _read_json(json_path)
            totals = aggregate_inventory(js, include_tech=bool(args.include_tech))
            print(f"[initial_import] Using: {json_path} (rows={len(totals)})", file=sys.stderr)
        except Exception as e:
            print(f"[initial_import] Using: {json_path} (rows=unknown) error={e}", file=sys.stderr)

        print(sql)
        return

if __name__ == "__main__":
    main()
