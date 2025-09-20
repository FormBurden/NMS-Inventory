#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
db_import_initial.py
Reads the decoder manifest (.cache/decoded/_manifest_recent.json) and emits SQL to STDOUT:
  - inserts/gets a row in nms_snapshots for each decoded JSON
  - parses the JSON heuristically and inserts nms_items rows (one per slot)

Usage:
  # generate SQL and pipe to MariaDB (recommended)
  python3 scripts/python/db_import_initial.py | mariadb -u nms_user -p -D nms_database

Options:
  --manifest PATH   : path to manifest (default: DATA_DIR/.cache/decoded/_manifest_recent.json)
  --limit N         : only import first N manifest entries (for testing)
  --dry-run         : parse JSON, show counts on STDERR, but emit no INSERTs
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Iterable, List, Tuple

# Project convention (per instruction #28)
try:
    from modules.config import DATA_DIR  # type: ignore
except Exception:
    DATA_DIR = str(Path(__file__).resolve().parents[2])

MANIFEST_DEFAULT = str(Path(DATA_DIR) / ".cache" / "decoded" / "_manifest_recent.json")

# -------------------------------
# tiny MySQL string escaper
# -------------------------------
def sql_str(s: str) -> str:
    """Return a single-quoted, escaped SQL literal."""
    return "'" + s.replace("\\", "\\\\").replace("'", "''") + "'"

def sql_dt(dt_iso: str) -> str:
    """
    Accept ISO-like strings, normalize to 'YYYY-MM-DD HH:MM:SS'.
    If string already looks like that, pass through.
    """
    try:
        # tolerate '2025-09-20T13:45:00.123456' or '2025-09-20T13:45:00'
        dt = dt_iso.replace("T", " ").split(".")[0]
        # Basic sanity check
        datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
        return sql_str(dt)
    except Exception:
        # last-ditch: just quote raw
        return sql_str(dt_iso)

# -------------------------------
# heuristics to infer inventory metadata
# -------------------------------
OWNER_TOKENS = [
    ("SUIT", ["Suit", "Player", "Exosuit"]),
    ("SHIP", ["Ship", "CurrentShip", "Spaceship"]),
    ("FREIGHTER", ["Freighter"]),
    ("VEHICLE", ["Vehicle", "VehicleInventory"]),
    ("STORAGE", ["Storage", "StorageContainer"]),
    ("PET", ["Pet", "Creature"]),
    ("BASE", ["Base"])
]

def infer_owner_type(path_stack: List[str]) -> str:
    p = " / ".join(path_stack)
    for label, hints in OWNER_TOKENS:
        for h in hints:
            if h.lower() in p.lower():
                return label
    return "UNKNOWN"

def infer_inventory_kind(path_stack: List[str]) -> str:
    p = " / ".join(path_stack).lower()
    if "tech" in p or "technology" in p:
        return "TECHONLY"
    if "cargo" in p:
        return "CARGO"
    return "GENERAL"

def infer_container_id(path_stack: List[str]) -> str:
    """
    Try to pull a stable container id from the path (e.g., storage container index).
    Falls back to empty string if we can't infer.
    """
    # Prefer explicit "StorageContainerXX"
    for seg in reversed(path_stack):
        m = re.search(r"(Storage(?:Container)?)(\d+)", seg, flags=re.I)
        if m:
            return f"{m.group(1).upper()}{m.group(2)}"
    # Otherwise any trailing number we can grab
    for seg in reversed(path_stack):
        m = re.search(r"(\d{1,3})", seg)
        if m:
            return m.group(1)
    return ""

def extract_item_type(slot: Dict[str, Any], path_stack: List[str]) -> str:
    # Prefer explicit inventory type if present
    t = slot.get("Type")
    if isinstance(t, dict):
        inv = t.get("InventoryType")
        if isinstance(inv, str) and inv:
            return inv
    # Fallback based on context
    p = " / ".join(path_stack).lower()
    if "tech" in p or "technology" in p:
        return "Technology"
    if "substance" in p:
        return "Substance"
    # Default
    return "Product"

# -------------------------------
# walk JSON, yield items
# -------------------------------
def walk_items(obj: Any, path_stack: List[str]=None) -> Iterable[Tuple[str,int,str,str,str]]:
    """
    Yield tuples: (resource_id, amount, owner_type, inventory_kind, container_id)
    Only accept dicts that look like inventory slots: must have 'Id' (str) and 'Amount' (int).
    """
    if path_stack is None:
        path_stack = []

    if isinstance(obj, dict):
        # slot-like?
        rid = obj.get("Id")
        amt = obj.get("Amount")
        if isinstance(rid, str) and isinstance(amt, int):
            owner = infer_owner_type(path_stack)
            inv   = infer_inventory_kind(path_stack)
            cont  = infer_container_id(path_stack)
            item_type = extract_item_type(obj, path_stack)
            yield (rid, amt, owner, inv, cont + "|" + item_type)  # stash item_type into the container key to carry it forward

        for k, v in obj.items():
            # Skip enormous binary-ish blobs if any (none expected from nmssavetool)
            if isinstance(k, str):
                path_stack.append(k)
                yield from walk_items(v, path_stack)
                path_stack.pop()

    elif isinstance(obj, list):
        for idx, v in enumerate(obj):
            path_stack.append(str(idx))
            yield from walk_items(v, path_stack)
            path_stack.pop()
			
def read_json_lenient(path: Path) -> dict | list:
    """
    Read bytes, strip BOM & NUL, trim, and parse JSON.
    If the file is empty or not JSON-looking, raise ValueError.
    """
    raw = path.read_bytes()
    # strip BOM
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    # remove all NULs
    if b"\x00" in raw:
        raw = raw.replace(b"\x00", b"")
    raw = raw.strip()
    if not raw:
        raise ValueError("empty after cleaning")
    # if there's junk before first { or [, attempt to slice from first JSON token
    first_obj = raw.find(b"{")
    first_arr = raw.find(b"[")
    pos = min(x for x in (first_obj, first_arr) if x != -1) if (first_obj != -1 or first_arr != -1) else -1
    if pos > 0:
        raw = raw[pos:]
    # decode
    txt = raw.decode("utf-8", errors="replace")
    # final trim just in case
    txt = txt.strip()
    if not txt or txt[0] not in "{[":
        raise ValueError("not a JSON object/array")
    return json.loads(txt)

# -------------------------------
# main
# -------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Emit SQL to import snapshots + items from decoder manifest.")
    ap.add_argument("--manifest", default=MANIFEST_DEFAULT, help="Path to _manifest_recent.json")
    ap.add_argument("--limit", type=int, default=0, help="Only import first N manifest entries (for testing)")
    ap.add_argument("--dry-run", action="store_true", help="Parse, report counts, emit no INSERTs")
    args = ap.parse_args()

    manifest_path = Path(args.manifest).expanduser().resolve()
    if not manifest_path.exists():
        print(f"[ERR] manifest not found: {manifest_path}", file=sys.stderr)
        sys.exit(2)

    meta = json.loads(manifest_path.read_text(encoding="utf-8"))
    items_meta = meta.get("items") or []
    if not isinstance(items_meta, list) or not items_meta:
        print("[ERR] manifest contains no 'items' array", file=sys.stderr)
        sys.exit(2)

    if args.limit and args.limit > 0:
        items_meta = items_meta[:args.limit]

    # Emit header
    if not args.dry_run:
        print("SET NAMES utf8mb4;")
        print("SET time_zone = '+00:00';")
        print("START TRANSACTION;")

    total_slots = 0
    for entry in items_meta:
        src = entry.get("source_path")
        root = entry.get("save_root", "")
        src_mtime = entry.get("source_mtime", "")
        dec_mtime = entry.get("decoded_mtime", "")
        out_json = entry.get("out_json")
        jhash = entry.get("json_sha256", "")

        if not (src and out_json):
            print(f"[warn] skipping manifest entry missing src/out_json: {entry}", file=sys.stderr)
            continue

        # Upsert snapshot row, capture @sid
        if not args.dry_run:
            print("-- snapshot upsert")
            print(
                "INSERT INTO nms_snapshots "
                "(source_path, save_root, source_mtime, decoded_mtime, json_sha256) VALUES ("
                f"{sql_str(src)}, {sql_str(root)}, {sql_dt(src_mtime)}, {sql_dt(dec_mtime)}, {sql_str(jhash)}"
                ") ON DUPLICATE KEY UPDATE "
                "snapshot_id = LAST_INSERT_ID(snapshot_id), "
                "decoded_mtime = VALUES(decoded_mtime), "
                "json_sha256 = VALUES(json_sha256);"
            )
            print("SET @sid := LAST_INSERT_ID();")

        # Parse JSON and prepare item INSERTs
        jpath = Path(out_json)
        try:
            data = json.loads(jpath.read_text(encoding="utf-8", errors="ignore"))
        except Exception as e:
            print(f"[warn] failed to parse JSON {out_json}: {e}", file=sys.stderr)
            continue

        # Per-container slot counters to ensure uniqueness
        container_counters: Dict[Tuple[str,str,str], int] = {}

        # We smuggled item_type with the container_id via walk_items (cont|type)
        # so we can keep a consistent type per logical container while counting slots.
        for (rid, amt, owner, inv, cont_and_type) in walk_items(data, []):
            if not isinstance(rid, str) or not isinstance(amt, int):
                continue

            # split back
            if "|" in cont_and_type:
                cont, itype = cont_and_type.split("|", 1)
            else:
                cont, itype = cont_and_type, "Product"

            # normalize fields
            rid_str = rid.strip()
            owner   = (owner or "UNKNOWN").upper()
            inv     = (inv or "GENERAL").upper()
            cont    = cont or ""

            ckey = (owner, inv, cont)
            slot_idx = container_counters.get(ckey, 0)
            container_counters[ckey] = slot_idx + 1

            if args.dry_run:
                total_slots += 1
                continue

            # INSERT item
            print(
                "INSERT INTO nms_items "
                "(snapshot_id, owner_type, inventory, container_id, slot_index, resource_id, amount, item_type) VALUES ("
                f"@sid, {sql_str(owner)}, {sql_str(inv)}, {sql_str(cont)}, {slot_idx}, {sql_str(rid_str)}, {amt}, {sql_str(itype)}"
                ");"
            )

        if args.dry_run:
            print(f"[dry-run] {out_json}: parsed {sum(container_counters.values())} slots", file=sys.stderr)

    if not args.dry_run:
        print("COMMIT;")

    if args.dry_run:
        print(f"[dry-run] total parsed slots: {total_slots}", file=sys.stderr)

if __name__ == "__main__":
    main()
