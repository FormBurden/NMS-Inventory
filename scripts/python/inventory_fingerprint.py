#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, sys
from typing import Any, Dict, Iterable, Tuple

HERE = os.path.dirname(__file__)
sys.path.append(HERE)                     # scripts/python
sys.path.append(os.path.join(HERE, "..")) # scripts/

# Reuse your decoder + helpers
from nms_hg_decoder import decode_to_json_bytes
from nms_extract_inventory import walk, obj_is_slot, is_progress_token

SANE_CAPS = {50, 100, 101, 200, 250, 500, 801, 1000, 1001, 2000, 9999}

def _amount(slot: dict) -> int:
    a = slot.get("1o9")
    cap = slot.get("F9q")
    if not isinstance(a, int) or not isinstance(cap, int):
        return 0
    if cap in SANE_CAPS and a <= cap:
        return max(a, 0)
    # fallback mirrors extractor’s approach (prefer the smaller plausible positive)
    candidates = [x for x in (a, cap) if isinstance(x, int) and x > 0]
    return min(candidates) if candidates else 0

def _infer_owner(path: Iterable[Any]) -> str:
    # Mirrors extractor’s owner inference (segment membership + dotted fallback)
    segs = {str(p) for p in path if isinstance(p, str)}
    if ";l5" in segs: owner = "SUIT"
    elif "P;m" in segs: owner = "SHIP"
    elif "<IP" in segs: owner = "FREIGHTER"
    elif "3Nc" in segs: owner = "STORAGE"
    elif "8ZP" in segs: owner = "VEHICLE"
    else:
        pstr = ".".join(str(p) for p in list(path)[-256:])
        if ".;l5." in pstr: owner = "SUIT"
        elif ".P;m." in pstr: owner = "SHIP"
        elif ".<IP." in pstr: owner = "FREIGHTER"
        elif ".3Nc." in pstr: owner = "STORAGE"
        elif ".8ZP." in pstr: owner = "VEHICLE"
        else: owner = "UNKNOWN"
    if owner == "FREIGHTER":
        owner = "FRIGATE"  # normalize like extractor
    return owner

def _load_json_from_hg(hg_path: str) -> Any:
    with open(hg_path, "rb") as f:
        raw = f.read()
    jb = decode_to_json_bytes(raw, debug=False)
    return json.loads(jb.decode("utf-8"))

def compute_rows(obj: Any):
    # Aggregate totals per (owner_type, resource_id)
    totals: Dict[Tuple[str, str], int] = {}
    for path, _parent, _key, val in walk(obj):
        if not isinstance(val, dict):
            continue
        if not obj_is_slot(val):
            continue
        rid = val.get("b2n")
        if is_progress_token(rid):
            continue
        amt = _amount(val)
        if amt <= 0:
            continue
        owner = _infer_owner(path)
        key = (owner, rid)
        totals[key] = totals.get(key, 0) + amt
    rows = [f"{o}|{rid}|{totals[(o, rid)]}" for (o, rid) in sorted(totals)]
    return rows

def fingerprint_rows(rows) -> str:
    payload = ";".join(rows)
    return hashlib.blake2b(payload.encode("utf-8"), digest_size=32).hexdigest()

def main():
    ap = argparse.ArgumentParser(description="Inventory-only fingerprint for NMS .hg")
    ap.add_argument("--hg", required=True, help="Path to save*.hg")
    args = ap.parse_args()
    data = _load_json_from_hg(args.hg)
    rows = compute_rows(data)
    print(fingerprint_rows(rows))

if __name__ == "__main__":
    sys.exit(main())
