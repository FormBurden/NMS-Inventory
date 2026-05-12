import argparse, hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple, Optional, Union

# Package-import shim for direct execution and legacy ledger imports.
# This file can be imported as ledger.cli_main by nms_resource_ledger.py,
# so the repo root must be available even when __package__ is not empty.
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Leaf imports only (avoid aggregator __init__ which imports db_conn with redacted password literal)
from scripts.python.pipeline.ledger.initial_import import _escape_sql  # type: ignore
from scripts.python.pipeline.ledger.inventory import aggregate_inventory
from scripts.python.pipeline.ledger.ts_utils import canonical_ts_from_file

def _load_manifest(path: Path) -> Dict[str, Any]:
    import json
    return json.loads(path.read_text(encoding="utf-8"))

def _infer_save_root(manifest: Dict[str, Any], item: Dict[str, Any], js: Dict[str, Any], json_path: Path) -> str:
    """
    Best-effort resolver for the original Hello Games save root.
    Priority:
      1) manifest['save_root'] or item['save_root']
      2) manifest/item meta: 'hg_root' or parent of 'hg_path'
      3) full-parse meta: js['_meta']['save_root'] or js['_meta']['hg_root'] or parent of js['_meta']['hg_path']
      4) fallback: parent of manifest/item 'source_path'
      5) last-resort: ''
    """
    def _parent(p: Optional[str]) -> Optional[str]:
        if not p: return None
        try:
            return str(Path(p).expanduser().resolve().parent)
        except Exception:
            return str(Path(p).parent)

    meta = js.get("_meta", {}) if isinstance(js, dict) else {}

    candidates: List[Optional[str]] = [
        manifest.get("save_root"),
        item.get("save_root"),
        manifest.get("hg_root"),
        item.get("hg_root"),
        meta.get("save_root"),
        meta.get("hg_root"),
        _parent(meta.get("hg_path")),
        _parent(item.get("hg_path")),
        _parent(manifest.get("hg_path")),
        _parent(item.get("source_path")),
        _parent(manifest.get("source_path")),
    ]

    for c in candidates:
        if c and str(c).strip():
            return str(c).strip()

    return ""


def _read_json(path: Path) -> Dict[str, Any]:
    import json
    return json.loads(path.read_text(encoding="utf-8"))

def _find_best_json(item: Dict[str, Any]) -> Optional[Path]:
    """
    Resolve the most useful JSON to aggregate, in order of preference:
      1) out_json (full-parse output) if present
      2) output/fullparse/<save>.full.json derived from decoded source_path
      3) cleaned JSON derived from decoded path: /decoded/<name>.json -> /cleaned/<name>.clean.json
      4) source_path (decoded json) as a last resort
    """
    out_json = item.get("out_json")
    if out_json:
        p = Path(out_json)
        if p.exists():
            return p

    source = item.get("source_path")
    if source:
        sp = Path(source)

        try:
            root = Path(__file__).resolve().parents[4]
            fullparse = root / "output" / "fullparse" / f"{sp.stem}.full.json"
            if fullparse.exists():
                return fullparse
        except Exception:
            pass

        try:
            parts = list(sp.parts)
            if "decoded" in parts:
                parts[parts.index("decoded")] = "cleaned"
                stem = sp.stem
                cleaned = Path(*parts[:-1]) / f"{stem}.clean.json"
                if cleaned.exists():
                    return cleaned
        except Exception:
            pass

        if sp.exists():
            return sp

    return None

def _emit_initial_sql(json_path: Path, *, save_root: str, include_tech: bool = False, use_mtime: bool = False) -> str:
    """
    Emit transactional SQL that:
      1) INSERT IGNORE nms_resources(resource_id) for any missing ids
      2) INSERT nms_snapshots(source_path, save_root) and capture @sid
      3) INSERT nms_items(snapshot_id, owner_type, inventory, slot_index, resource_id, amount) VALUES (...)
    """
    js = _read_json(json_path)
    totals = aggregate_inventory(js, include_tech=include_tech)
    if not totals:
        return "/* no snapshot rows generated */\n"

    def norm_owner(s: str) -> str:
        s = (s or "").strip().lower()
        if s == "character": return "Character"
        if s == "ship": return "Ship"
        if s == "vehicle": return "Vehicle"
        if s == "freighter": return "Freighter"
        if s == "storage": return "Storage"
        if s == "base": return "Base"
        return "Unknown"

    def norm_inv(s: str) -> str:
        s = (s or "").strip().lower()
        if s == "general": return "General"
        if s in ("tech", "technology"): return "Technology"
        if s == "cargo": return "Cargo"
        return "General"

    resource_ids: set[str] = set()
    slot_counters = defaultdict(int)
    item_rows: List[str] = []

    for (owner_type, inventory, resource_id), amt in sorted(totals.items(), key=lambda x: (x[0][0], x[0][1], x[0][2])):
        owner_sql = _escape_sql(norm_owner(str(owner_type)))
        inv_sql = _escape_sql(norm_inv(str(inventory)))
        rid_sql = _escape_sql(str(resource_id))
        resource_ids.add(rid_sql)

        slot_index = slot_counters[(owner_sql, inv_sql)]
        slot_counters[(owner_sql, inv_sql)] += 1
        item_rows.append(
            f"(@sid, '{owner_sql}', '{inv_sql}', {slot_index}, '{rid_sql}', {int(amt)}, 'unknown')"
        )

    if not item_rows:
        return "/* no snapshot rows generated */\n"

    resources_values = ",\n".join(f"('{rid}')" for rid in sorted(resource_ids))
    source_path_sql = _escape_sql(json_path.as_posix())
    save_root_sql = _escape_sql(save_root or "")

    try:
        _epoch = int(json_path.stat().st_mtime)
    except Exception:
        _ts = canonical_ts_from_file(json_path, use_mtime=True)
        _epoch = int(_ts.timestamp())

    source_mtime_sql = f"FROM_UNIXTIME({_epoch})"
    json_sha256_sql = hashlib.sha256(json_path.read_bytes()).hexdigest()

    sql_lines: List[str] = []
    sql_lines.append("SET FOREIGN_KEY_CHECKS=0;")
    sql_lines.append("START TRANSACTION;")

    if resources_values:
        sql_lines.append("INSERT IGNORE INTO nms_resources(resource_id) VALUES")
        sql_lines.append(resources_values + ";")

    sql_lines.append(
        f"INSERT INTO nms_snapshots(source_path, save_root, source_mtime, json_sha256) "
        f"VALUES ('{source_path_sql}', '{save_root_sql}', {source_mtime_sql}, '{json_sha256_sql}');"
    )
    sql_lines.append("SET @sid := LAST_INSERT_ID();")

    sql_lines.append("INSERT INTO nms_items(snapshot_id, owner_type, inventory, slot_index, resource_id, amount, item_type) VALUES")
    sql_lines.append(",\n".join(item_rows) + ";")

    sql_lines.append("COMMIT;")
    sql_lines.append("SET FOREIGN_KEY_CHECKS=1;")
    return "\n".join(sql_lines) + "\n"

def main() -> None:
    import sys

    argv = sys.argv[1:]
    if argv and argv[0] == "initial_import":
        p = argparse.ArgumentParser(prog="nms-inventory-cli initial_import")
        p.add_argument("cmd")
        p.add_argument("--manifest", required=True, type=Path)
        p.add_argument("--db-name", required=False)
        p.add_argument("--include-tech", action="store_true", default=False)
        p.add_argument("--use-mtime", action="store_true", default=False)
        args = p.parse_args(argv)

        manifest = _load_manifest(args.manifest)
        items = manifest.get("items") or []
        if not items:
            print("/* no snapshot rows generated */")
            return

        item0 = items[0]
        json_path = _find_best_json(item0)
        if not json_path or not json_path.exists():
            print("/* no snapshot rows generated */")
            print(f"[initial_import] No usable JSON found for item: {item0}", file=sys.stderr)
            return

        try:
            js_for_root = _read_json(json_path)
        except Exception:
            js_for_root = {}
        save_root = _infer_save_root(manifest, item0, js_for_root, json_path)

        sql = _emit_initial_sql(
            json_path,
            save_root=save_root,
            include_tech=bool(args.include_tech),
            use_mtime=bool(args.use_mtime),
        )

        try:
            js = _read_json(json_path)
            totals = aggregate_inventory(js, include_tech=bool(args.include_tech))
            print(f"[initial_import] Using: {json_path} (rows={len(totals)})", file=sys.stderr)
        except Exception as e:
            print(f"[initial_import] Using: {json_path} (rows=unknown) error={e}", file=sys.stderr)

        print(sql)
        return

    p = argparse.ArgumentParser(prog="nms-inventory-ledger")
    p.add_argument("--saves", required=False, type=Path)
    p.add_argument("--baseline-db-table", default="nms_initial_items")
    p.add_argument("--baseline-snapshot", default="latest")
    p.add_argument("--db-write-ledger", action="store_true", default=False)
    p.add_argument("--db-env", type=Path, default=Path(".env"))
    p.add_argument("--db-ledger-table", default="nms_ledger_deltas")
    p.add_argument("--session-minutes", type=int, default=120)
    p.add_argument("--use-mtime", action="store_true", default=False)
    p.add_argument("--include-tech", action="store_true", default=True)
    args = p.parse_args(argv)

    from scripts.python.pipeline.ledger.cli_run import run_ledger
    run_ledger(args)

if __name__ == "__main__":
    main()
