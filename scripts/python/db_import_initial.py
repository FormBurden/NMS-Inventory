#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
db_import_initial.py
Reads .cache/decoded/_manifest_recent.json and emits SQL to STDOUT:
  - upsert nms_snapshots (captures snapshot_id in @sid)
  - walk JSON and insert rows into nms_items

Supports nmssavetool's obfuscated JSON:
  - caret resource ids like "^ANTIMATTER" found anywhere in a dict
  - amount comes from '1o9' (obfuscated) or 'Amount' (readable) ONLY
  - ignores 'F9q' (stack cap) so totals aren't inflated
  - filters out non-inventory noise and Technology rows (GUI wants mats)
  - stable container_id + slot_index; slot_index uses digits AFTER 'IDX'
  - ON DUPLICATE KEY UPDATE to avoid unique-key aborts

Usage:
  python3 scripts/python/db_import_initial.py --manifest .cache/decoded/_manifest_recent.json \
  | mariadb -u nms_user -p -D nms_database
"""

from __future__ import annotations

import argparse, json, re, sys, hashlib
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
# MySQL escapers
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
# Robust JSON reader
# -------------------------------
def read_json_lenient(path: Path) -> dict | list:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"): raw = raw[3:]
    if b"\x00" in raw: raw = raw.replace(b"\x00", b"")
    raw = raw.strip()
    if not raw: raise ValueError("empty JSON")
    i_obj, i_arr = raw.find(b"{"), raw.find(b"[")
    pos = min([x for x in (i_obj, i_arr) if x != -1]) if (i_obj != -1 or i_arr != -1) else -1
    if pos > 0: raw = raw[pos:]
    txt = raw.decode("utf-8", errors="replace").strip()
    if not txt or txt[0] not in "{[}":  # allow single-object/array
        raise ValueError("not JSON")
    return json.loads(txt)

# -------------------------------
# Heuristics: Id / Amount / Type
# -------------------------------
ID_KEYS = ("Id", "ID", "Symbol", "ProductId", "SubstanceId", "ResourceId", "TypeId")

def get_id_from(obj: Dict[str, Any]) -> str | None:
    # readable
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
    # obfuscated caret id anywhere in this dict
    for v in obj.values():
        if isinstance(v, str) and re.match(r"^\^[A-Z0-9_]+$", v):
            return v
    return None

def get_amount_from(obj: Dict[str, Any]) -> int | None:
    # ONLY these: '1o9' (obf) or 'Amount' (readable). Never 'F9q'.
    v = obj.get("1o9")
    if isinstance(v, (int, float)): return int(v)
    v = obj.get("Amount")
    if isinstance(v, (int, float)): return int(v)
    if isinstance(v, str) and v.strip().isdigit(): return int(v.strip())
    return None

def get_item_type(obj: Dict[str, Any], path_stack: List[str]) -> str:
    t = obj.get("Type")
    if isinstance(t, dict):
        inv = t.get("InventoryType")
        if isinstance(inv, str) and inv: return inv
    # obf hint
    for dv in obj.values():
        if isinstance(dv, dict):
            for sv in dv.values():
                if isinstance(sv, str) and sv in ("Product","Substance","Technology"):
                    return sv
    p = " / ".join(path_stack).lower()
    if "tech" in p or "technology" in p: return "Technology"
    if "substance" in p: return "Substance"
    return "Product"


# -------------------------------
# Owner / Inventory / Container
# -------------------------------
OWNER_TOKENS = [
    ("SUIT",      ["Suit","Player","Exosuit","PlayerStateData","PlayerInventory","PlayerCharacter","Character","Inventory"]),
    ("SHIP",      ["Ship","CurrentShip","Spaceship","ShipOwnership","SpaceShip"]),
    ("FREIGHTER", ["Freighter","CapitalShip"]),
    ("VEHICLE",   ["Vehicle","VehicleInventory","Exocraft"]),
    ("STORAGE",   ["Storage","StorageContainer","Chest","BaseStorage"]),
    ("PET",       ["Pet","Creature"]),
    ("BASE",      ["Base","BaseBuilding"]),
]
ALLOWED_OWNERS = {"SUIT","SHIP","FREIGHTER","VEHICLE","STORAGE","UNKNOWN"}

def infer_owner_type(path_stack: List[str]) -> str:
    p = " / ".join(path_stack).lower()
    for label, hints in OWNER_TOKENS:
        if any(h.lower() in p for h in hints): return label
    return "UNKNOWN"

def infer_inventory_kind(path_stack: List[str]) -> str:
    p = " / ".join(path_stack).lower()
    if "tech" in p or "technology" in p: return "TECHONLY"
    if "cargo" in p: return "CARGO"
    return "GENERAL"

def path_fingerprint(path_stack: List[str]) -> str:
    tail = "/".join(path_stack[-8:])
    h = hashlib.sha1(tail.encode("utf-8", errors="ignore")).hexdigest()
    return "C" + h[:6].upper()

def infer_container_id(obj: Dict[str, Any], path_stack: List[str], owner_type: str) -> str:
    # explicit Index (readable)
    idx = obj.get("Index")
    if isinstance(idx, dict):
        x = idx.get("X"); y = idx.get("Y"); z = idx.get("Z")
        if isinstance(x, int) and isinstance(y, int):
            base = f"IDX{int(x)}x{int(y)}" + (f"x{int(z)}" if isinstance(z, int) else "")
        else:
            base = ""
    else:
        base = ""
    # obf: any child dict with 2–3 ints
    if not base:
        for dv in obj.values():
            if isinstance(dv, dict):
                ints = [v for v in dv.values() if isinstance(v, int)]
                if 2 <= len(ints) <= 3:
                    base = "IDX" + "x".join(str(int(x)) for x in ints[:3])
                    break
    # storage in path
    if not base:
        for seg in reversed(path_stack):
            m = re.search(r"(Storage(?:Container)?)(\d+)", seg, flags=re.I)
            if m:
                base = f"{m.group(1).upper()}{m.group(2)}"; break
    # trailing number
    if not base:
        for seg in reversed(path_stack):
            m = re.search(r"(\d{1,3})$", seg)
            if m: base = m.group(1); break
    # disambiguate UNKNOWN + IDX… with fingerprint
    if owner_type == "UNKNOWN" and base.startswith("IDX"):
        base = f"{path_fingerprint(path_stack)}-{base}"
    return base

# -------------------------------
# Filter for nmssavetool slot dicts (to avoid UI/quest noise)
# -------------------------------
def looks_like_nmst_slot(obj: Dict[str, Any]) -> bool:
    rid = None
    for v in obj.values():
        if isinstance(v, str) and re.match(r"^\^[A-Z0-9_]+$", v): rid = v; break
    if not rid: return False
    has_index = False
    for dv in obj.values():
        if isinstance(dv, dict):
            ints = [v for v in dv.values() if isinstance(v, int)]
            if 2 <= len(ints) <= 3: has_index = True; break
    if not has_index: return False
    has_type = False
    for dv in obj.values():
        if isinstance(dv, dict):
            if any(isinstance(sv, str) and sv in ("Product","Substance","Technology") for sv in dv.values()):
                has_type = True; break
    if not has_type: return False
    if sum(1 for v in obj.values() if isinstance(v, bool)) < 2: return False
    return True

# -------------------------------
# Walk JSON → yield items
# -------------------------------
def walk_items(obj: Any, path_stack: List[str] | None = None) -> Iterable[Tuple[str,int,str,str,str,str]]:
    if path_stack is None:
        path_stack = []

    if isinstance(obj, dict):
        rid = get_id_from(obj)
        amt = get_amount_from(obj)
        if rid is not None and amt is not None:
            # Skip obvious UI/tooltip resources only; otherwise accept caret IDs.
            if not rid.startswith("^UI_"):
                owner = infer_owner_type(path_stack)
                inv   = infer_inventory_kind(path_stack)
                cont  = infer_container_id(obj, path_stack, owner)
                itype = get_item_type(obj, path_stack) or "Product"
                yield (rid, int(amt), owner, inv, cont, itype)

        # Recurse children
        for k, v in obj.items():
            path_stack.append(str(k))
            yield from walk_items(v, path_stack)
            path_stack.pop()

    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            path_stack.append(str(i))
            yield from walk_items(v, path_stack)
            path_stack.pop()


# -------------------------------
# slot_index helpers
# -------------------------------
def _tuple_to_int(nums: List[int]) -> int:
    out = 0
    for n in nums:
        out = out * 1000 + int(n)
    return out

def compute_slot_index(cont: str, owner: str, inv: str, per_key_counter: Dict[Tuple[str,str,str], int]) -> int:
    if "IDX" in cont:
        idx_part = cont[cont.rfind("IDX"):]
        nums = [int(x) for x in re.findall(r"\d+", idx_part)]
        if nums:
            return _tuple_to_int(nums)
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
        print(f"[ERR] manifest not found: {manifest_path}", file=sys.stderr); sys.exit(2)

    meta = json.loads(manifest_path.read_text(encoding="utf-8"))
    items_meta = meta.get("items") or []
    if not isinstance(items_meta, list) or not items_meta:
        print("[ERR] manifest contains no 'items' array", file=sys.stderr); sys.exit(2)
    if args.limit and args.limit > 0:
        items_meta = items_meta[:args.limit]

    if not args.dry_run:
        print("SET NAMES utf8mb4;")
        print("SET time_zone = '+00:00';")
        print("START TRANSACTION;")

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

        # Deduplicate + filter in-memory for this snapshot
        per_key_counter: Dict[Tuple[str,str,str], int] = {}
        seen: Dict[Tuple[str,str,str,int,str], Tuple[int,str]] = {}

        for (rid, amt, owner, inv, cont, itype) in walk_items(data, []):
            owner = (owner or "UNKNOWN").upper()
            inv   = (inv or "GENERAL").upper()
            cont  = cont or ""
            itype = (itype or "Product")

            # --- filters to drop junk/noise ---
            if owner not in ALLOWED_OWNERS:  # drop UNKNOWN/BASE/PET/etc.
                continue
            if itype == "Technology":        # GUI wants mats, not tech
                continue
            if not isinstance(amt, int) or amt <= 0:  # ignore empty placeholders
                continue
            # -----------------------------------

            slot_index = compute_slot_index(cont, owner, inv, per_key_counter)
            skey = (owner, inv, cont, slot_index, rid)
            prev = seen.get(skey)
            if prev is None:
                seen[skey] = (int(amt), itype)
            else:
                prev_amt, prev_type = prev
                if int(amt) > prev_amt:
                    seen[skey] = (int(amt), itype)

        if args.dry_run:
            print(f"[dry-run] {out_json}: parsed {len(seen)} slots", file=sys.stderr)
            continue

        # Emit with upsert to avoid unique-key aborts
        for (owner, inv, cont, slot_index, rid), (amt, itype) in seen.items():
            print(
                "INSERT INTO nms_items "
                "(snapshot_id, owner_type, inventory, container_id, slot_index, resource_id, amount, item_type) VALUES ("
                f"@sid, {sql_str(owner)}, {sql_str(inv)}, {sql_str(cont)}, {slot_index}, {sql_str(rid)}, {amt}, {sql_str(itype)}"
                ") ON DUPLICATE KEY UPDATE "
                "resource_id = VALUES(resource_id), "
                "amount = GREATEST(nms_items.amount, VALUES(amount)), "
                "item_type = VALUES(item_type);"
            )

    if not args.dry_run:
        print("COMMIT;")

if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        try: sys.stdout.close()
        except Exception: pass
        sys.exit(1)
