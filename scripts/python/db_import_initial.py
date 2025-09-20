#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
db_import_initial.py
Reads .cache/decoded/_manifest_recent.json and emits SQL to STDOUT:
  - upsert nms_snapshots (captures snapshot_id in @sid)
  - walk JSON and insert rows into nms_items

Now supports both human-readable decoder JSON and nmssavetool's obfuscated JSON:
  - resource ids like "^ANTIMATTER" found even when keys are obfuscated
  - amounts inferred from common obfuscated keys (e.g., 'F9q', '1o9') or max int fallback
  - slot index built from embedded index dicts (e.g., {'>Qh':1,'XJ>':0} -> 'IDX1x0')
  - filters exclude non-inventory '^UI_*' strings
  - container_id gains a short path fingerprint prefix when owner_type cannot be inferred,
    preventing duplicate-key collisions between distinct inventories that share the same 'IDX#x#'

Usage:
  python3 scripts/python/db_import_initial.py | mariadb -u nms_user -p -D nms_database

Options:
  --manifest PATH   Path to manifest (default: DATA_DIR/.cache/decoded/_manifest_recent.json)
  --limit N         Only import first N entries
  --dry-run         Parse and report counts, emit no SQL
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Iterable, List, Tuple

# DATA_DIR fallback
try:
    from modules.config import DATA_DIR  # type: ignore
except Exception:
    DATA_DIR = str(Path(__file__).resolve().parents[2])

MANIFEST_DEFAULT = str(Path(DATA_DIR) / ".cache" / "decoded" / "_manifest_recent.json")

# -------------------------------
# Tiny MySQL escapers
# -------------------------------
def sql_str(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "''") + "'"

def sql_dt(dt_iso: str) -> str:
    try:
        dt = dt_iso.replace("T", " ").split(".")[0]
        datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
        return sql_str(dt)
    except Exception:
        return sql_str(dt_iso)

# -------------------------------
# Robust JSON reader (strip BOM/NUL, slice to first { or [)
# -------------------------------
def read_json_lenient(path: Path) -> dict | list:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    if b"\x00" in raw:
        raw = raw.replace(b"\x00", b"")
    raw = raw.strip()
    if not raw:
        raise ValueError("empty JSON")
    i_obj, i_arr = raw.find(b"{"), raw.find(b"[")
    pos = min([x for x in (i_obj, i_arr) if x != -1]) if (i_obj != -1 or i_arr != -1) else -1
    if pos > 0:
        raw = raw[pos:]
    txt = raw.decode("utf-8", errors="replace").strip()
    if not txt or txt[0] not in "{[":
        raise ValueError("not JSON")
    return json.loads(txt)

# -------------------------------
# Heuristics: pull Id / Amount / Type (readable + obfuscated)
# -------------------------------
ID_KEYS = ("Id", "ID", "Symbol", "ProductId", "SubstanceId", "ResourceId", "TypeId")

def get_id_from(obj: Dict[str, Any]) -> str | None:
    # human-readable
    for k in ID_KEYS:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    d = obj.get("Default")
    if isinstance(d, dict):
        for k in ID_KEYS:
            v = d.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    # obfuscated: any value like "^ANTIMATTER"
    for v in obj.values():
        if isinstance(v, str) and re.match(r"^\^[A-Z0-9_]+$", v):
            return v
    return None

AMOUNT_PRIORITIES = ("Amount", "F9q", "1o9", "StackSize")

def get_amount_from(obj: Dict[str, Any]) -> int | None:
    # prefer common keys
    for k in AMOUNT_PRIORITIES:
        v = obj.get(k)
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str) and v.strip().isdigit():
            return int(v.strip())
        if isinstance(v, dict):
            w = v.get("Value")
            if isinstance(w, (int, float)):
                return int(w)
            if isinstance(w, str) and w.strip().isdigit():
                return int(w.strip())
    # fallback: max integer value in this dict
    ints = [v for v in obj.values() if isinstance(v, int)]
    if ints:
        return max(ints)
    return None

def get_item_type(obj: Dict[str, Any], path_stack: List[str]) -> str:
    # human-readable
    t = obj.get("Type")
    if isinstance(t, dict):
        inv = t.get("InventoryType")
        if isinstance(inv, str) and inv:
            return inv
    # obfuscated: look into any nested dict for 'Product'/'Substance'/'Technology'
    for dv in obj.values():
        if isinstance(dv, dict):
            for sv in dv.values():
                if isinstance(sv, str) and sv in ("Product","Substance","Technology"):
                    return sv
    # context fallback
    p = " / ".join(path_stack).lower()
    if "tech" in p or "technology" in p:
        return "Technology"
    if "substance" in p:
        return "Substance"
    return "Product"

# -------------------------------
# Owner / Inventory inference
# -------------------------------
OWNER_TOKENS = [
    ("SUIT", ["Suit", "Player", "Exosuit", "PlayerStateData"]),
    ("SHIP", ["Ship", "CurrentShip", "Spaceship", "ShipOwnership"]),
    ("FREIGHTER", ["Freighter"]),
    ("VEHICLE", ["Vehicle", "VehicleInventory"]),
    ("STORAGE", ["Storage", "StorageContainer"]),
    ("PET", ["Pet", "Creature"]),
    ("BASE", ["Base"]),
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

def path_fingerprint(path_stack: List[str]) -> str:
    """
    Short, stable fingerprint for the *context* where the slot was found.
    Helps disambiguate when owner_type is UNKNOWN and container_id like 'IDX1x2' repeats
    across different inventories in obfuscated JSON.
    """
    # Take only the last ~8 nodes to avoid giant strings, then hash.
    tail = "/".join(path_stack[-8:])
    h = hashlib.sha1(tail.encode("utf-8", errors="ignore")).hexdigest()
    # return a short base16 tag
    return "C" + h[:6].upper()

def infer_container_id(obj: Dict[str, Any], path_stack: List[str], owner_type: str) -> str:
    # human-readable: explicit Index
    idx = obj.get("Index")
    if isinstance(idx, dict):
        x = idx.get("X"); y = idx.get("Y"); z = idx.get("Z")
        if isinstance(x, int) and isinstance(y, int):
            base = f"IDX{int(x)}x{int(y)}" + (f"x{int(z)}" if isinstance(z, int) else "")
        else:
            base = ""
    else:
        base = ""
    # obfuscated: any child dict with 2-3 ints -> treat as index tuple
    if not base:
        for dv in obj.values():
            if isinstance(dv, dict):
                ints = [v for v in dv.values() if isinstance(v, int)]
                if 2 <= len(ints) <= 3:
                    base = "IDX" + "x".join(str(int(x)) for x in ints[:3])
                    break
    # scan path segments for storage ids
    if not base:
        for seg in reversed(path_stack):
            m = re.search(r"(Storage(?:Container)?)(\d+)", seg, flags=re.I)
            if m:
                base = f"{m.group(1).upper()}{m.group(2)}"
                break
    # trailing number
    if not base:
        for seg in reversed(path_stack):
            m = re.search(r"(\d{1,3})$", seg)
            if m:
                base = m.group(1)
                break
    # If owner is UNKNOWN and base looks generic (IDX...), add a short path fingerprint
    if owner_type == "UNKNOWN" and base.startswith("IDX"):
        base = f"{path_fingerprint(path_stack)}-{base}"
    return base

# -------------------------------
# Strict filter for nmssavetool slot dicts
# -------------------------------
def looks_like_nmst_slot(obj: Dict[str, Any]) -> bool:
    """For obfuscated JSON, ensure it's a real inventory slot (not UI/quest)."""
    # resource id like ^SOMETHING
    rid = None
    for v in obj.values():
        if isinstance(v, str) and re.match(r"^\^[A-Z0-9_]+$", v):
            rid = v
            break
    if not rid:
        return False
    # embedded index dict with 2-3 ints
    has_index = False
    for dv in obj.values():
        if isinstance(dv, dict):
            ints = [v for v in dv.values() if isinstance(v, int)]
            if 2 <= len(ints) <= 3:
                has_index = True; break
    if not has_index:
        return False
    # embedded type dict with 'Product'/'Substance'/'Technology'
    has_type = False
    for dv in obj.values():
        if isinstance(dv, dict):
            if any(isinstance(sv, str) and sv in ("Product","Substance","Technology") for sv in dv.values()):
                has_type = True; break
    if not has_type:
        return False
    # slot dicts typically carry a couple of booleans too
    if sum(1 for v in obj.values() if isinstance(v, bool)) < 2:
        return False
    return True

# -------------------------------
# Walk JSON looking for slot-like dicts
# -------------------------------
def walk_items(obj: Any, path_stack: List[str] | None = None) -> Iterable[Tuple[str,int,str,str,str,str]]:
    """Yield: (resource_id, amount, owner_type, inventory_kind, container_id, item_type)."""
    if path_stack is None:
        path_stack = []

    if isinstance(obj, dict):
        rid = get_id_from(obj)
        amt = get_amount_from(obj)
        itype = get_item_type(obj, path_stack) if rid is not None else None

        if rid is not None and amt is not None:
            # is this readable (explicit Type/Index) or obfuscated?
            has_explicit_type = isinstance(obj.get("Type"), dict) and isinstance(obj["Type"].get("InventoryType"), str)
            idx_obj = obj.get("Index")
            has_explicit_index = isinstance(idx_obj, dict) and isinstance(idx_obj.get("X"), int) and isinstance(idx_obj.get("Y"), int)
            is_readable = has_explicit_type or has_explicit_index

            if rid.startswith("^") and not is_readable and not looks_like_nmst_slot(obj):
                pass  # skip non-slot '^' records (quests, UI strings, etc.)
            elif rid.startswith("^UI_") and not looks_like_nmst_slot(obj):
                pass
            else:
                owner = infer_owner_type(path_stack)
                inv   = infer_inventory_kind(path_stack)
                cont  = infer_container_id(obj, path_stack, owner)
                yield (rid, int(amt), owner, inv, cont, itype or "Product")

        for k, v in obj.items():
            path_stack.append(str(k))
            yield from walk_items(v, path_stack)
            path_stack.pop()

    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            path_stack.append(str(i))
            yield from walk_items(v, path_stack)
            path_stack.pop()

def _tuple_to_int(nums: List[int]) -> int:
    out = 0
    for n in nums:
        out = out * 1000 + int(n)
    return out

def compute_slot_index(cont: str, owner: str, inv: str, per_key_counter: Dict[Tuple[str,str,str], int]) -> int:
    """
    Build a stable, bounded integer index for the slot.
    If container_id contains 'IDX', only use the digits AFTER the last 'IDX' token.
    Otherwise, fall back to a per-(owner,inv,cont) counter starting at 0.
    """
    # Only look at the portion after the last 'IDX'
    if "IDX" in cont:
        idx_part = cont[cont.rfind("IDX"):]  # e.g., 'IDX1x2', 'IDX0x0'
        nums = [int(x) for x in re.findall(r"\d+", idx_part)]
        if nums:
            return _tuple_to_int(nums)

    # Fallback: counter per (owner, inv, cont)
    ckey = (owner, inv, cont)
    idx = per_key_counter.get(ckey, 0)
    per_key_counter[ckey] = idx + 1
    return idx


# -------------------------------
# Main
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

        if not args.dry_run:
            # Snapshot upsert + capture @sid
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

        # Parse JSON
        jpath = Path(out_json)
        try:
            data = read_json_lenient(jpath)
        except Exception as e:
            print(f"[warn] failed to parse JSON {out_json}: {e}", file=sys.stderr)
            continue

        # Deduplicate within a single snapshot by (owner, inv, cont, slot_index, rid)
        # We also need a stable slot_index: if cont looks like IDX..., build from digits; else use a counter per (owner,inv,cont)
        per_key_counter: Dict[Tuple[str,str,str], int] = {}
        seen: Dict[Tuple[str,str,str,int,str], Tuple[int,str]] = {}

        emitted = 0
        for (rid, amt, owner, inv, cont, itype) in walk_items(data, []):
            owner = (owner or "UNKNOWN").upper()
            inv   = (inv or "GENERAL").upper()
            cont  = cont or ""

            # compute slot_index
            slot_index = compute_slot_index(cont, owner, inv, per_key_counter)


            skey = (owner, inv, cont, slot_index, rid)
            prev = seen.get(skey)
            if prev is None:
                seen[skey] = (int(amt), itype or "Product")
            else:
                # keep max amount if duplicates of exact same slot+rid arise
                prev_amt, prev_type = prev
                if int(amt) > prev_amt:
                    seen[skey] = (int(amt), itype or prev_type)

        if args.dry_run:
            total_slots += len(seen)
            print(f"[dry-run] {out_json}: parsed {len(seen)} slots", file=sys.stderr)
            continue

        # Emit rows with ON DUPLICATE KEY UPDATE to avoid mariadb aborting on duplicates
        for (owner, inv, cont, slot_index, rid), (amt, itype) in seen.items():
            rid_str = rid
            print(
                "INSERT INTO nms_items "
                "(snapshot_id, owner_type, inventory, container_id, slot_index, resource_id, amount, item_type) VALUES ("
                f"@sid, {sql_str(owner)}, {sql_str(inv)}, {sql_str(cont)}, {slot_index}, {sql_str(rid_str)}, {amt}, {sql_str(itype)}"
                ") ON DUPLICATE KEY UPDATE "
                "resource_id = VALUES(resource_id), "
                "amount = GREATEST(nms_items.amount, VALUES(amount)), "
                "item_type = VALUES(item_type);"
            )
            emitted += 1

    if not args.dry_run:
        print("COMMIT;")

    if args.dry_run:
        print(f"[dry-run] total parsed slots: {total_slots}", file=sys.stderr)

if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        # Graceful exit when downstream closes the pipe (e.g., mysql error)
        try:
            sys.stdout.close()
        except Exception:
            pass
        sys.exit(1)
