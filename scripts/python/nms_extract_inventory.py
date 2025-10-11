#!/usr/bin/env python3
import argparse, json, sys, csv, hashlib, os
from collections import defaultdict, deque

GOOD_TYPES = {"Substance", "Product"}
# typical stack caps we consider "sane"
SANE_CAPS = {50, 100, 101, 200, 250, 500, 801, 1000, 1001, 2000, 9999}

# deny-list for progress/season tokens
def is_progress_token(rid: str) -> bool:
    if not rid or not isinstance(rid, str): return False
    if not rid.startswith("^"): return False
    stem = rid[1:]
    bad_prefixes = ("SMUGGLE_", "FLYER", "BIGGS_", "POLICE_", "GET_")
    if any(stem.startswith(p) for p in bad_prefixes): return True
    # expedition season counters like ^S19_*
    if len(stem) >= 4 and stem[0] == "S" and stem[1].isdigit() and stem[2].isdigit():
        if stem[3] == "_": return True
    return False

def load_json(path):
    with open(path, "rb") as f:
        return json.loads(f.read().decode("utf-8"))

def walk(obj):
    """Yield (path_list, parent_dict, key_of_parent, obj_dict) for every dict."""
    stack = deque([([], None, None, obj)])
    while stack:
        path, parent, pkey, val = stack.pop()
        if isinstance(val, dict):
            yield (path, parent, pkey, val)
            for k, v in val.items():
                stack.append((path + [k], val, k, v))
        elif isinstance(val, list):
            for i, v in enumerate(val):
                stack.append((path + [i], val, i, v))

def path_has_bad_context(path_list):
    # ignore any dict that sits under a segment named like 'RQA' or 'b69' or 'JWK'
    for seg in path_list:
        if isinstance(seg, str) and (seg == "RQA" or seg == "b69" or seg == "JWK"):
            return True
    return False

def dict_get(d, key, default=None):
    return d.get(key, default) if isinstance(d, dict) else default

def obj_is_slot(d):
    # Must look like a real slot object
    # shape: {'Vn8': {'elv':'Substance'|'Product'}, 'b2n':'^ID', '1o9':int, 'F9q':int, ...}
    if not isinstance(d, dict): return False
    idv = d.get("b2n")
    v8  = dict_get(d, "Vn8", {})
    elv = dict_get(v8, "elv")
    a   = d.get("1o9")
    cap = d.get("F9q")
    if (isinstance(idv, str) and idv.startswith("^")
        and isinstance(elv, str) and elv in GOOD_TYPES
        and isinstance(a, int) and isinstance(cap, int)):
        # sanity on amounts: ignore -1 and crazy inversions
        if a < 0: return False
        # some junk records have a>cap with tiny caps; prefer slots where cap looks plausible
        if cap not in SANE_CAPS and a > cap and a >= 9999:
            return False
        return True
    return False

def path_signature(path_list):
    # make a stable-ish container signature from a prefix of the path
    # we purposely exclude indexes to avoid per-run variance
    key_parts = [str(p) for p in path_list if isinstance(p, str)]
    raw = "/".join(key_parts)
    h = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return f"SIG:{h}"

def main():
    ap = argparse.ArgumentParser(description="Extract real inventory totals from decoded NMS save JSON")
    ap.add_argument("--json", required=True, help="Decoded save JSON (UTF-8)")
    ap.add_argument("--out-totals", default="output/totals.csv", help="CSV of item totals")
    ap.add_argument("--out-slots", default="", help="Optional CSV of per-slot rows")
    args = ap.parse_args()

    data = load_json(args.json)

    totals = defaultdict(int)
    slots_rows = []
    container_owner = {}
    auto_slot_counter = defaultdict(int)


    for path, parent, pkey, obj in walk(data):
        if path_has_bad_context(path):
            continue
        if not obj_is_slot(obj):
            continue

        rid = obj["b2n"]
        if is_progress_token(rid):
            continue

        amount = obj["1o9"]
        cap    = obj["F9q"]

        # prefer obviously sane combos
        if cap in SANE_CAPS and amount <= cap:
            amt = amount
        else:
            # fallback: pick the smaller positive of the two if one looks like a cap
            candidates = [x for x in (amount, cap) if isinstance(x, int) and x > 0]
            amt = min(candidates) if candidates else 0

        if amt <= 0:
            continue

        # infer inventory bucket from a small hint in obj['3ZH'] if present
        inv = "GENERAL"
        z = dict_get(obj, "3ZH", {})
        # '>Qh' and 'XJ>' seem to correlate with grid type; roughly map a few heuristics
        qh = z.get(">Qh")
        xj = z.get("XJ>")
        if isinstance(qh, int) and isinstance(xj, int):
            # very rough: if either looks > 4, treat as CARGO-ish (bigger caps)
            if amt > 500 or (qh >= 5 or xj >= 2):
                inv = "CARGO"

        # owner inference: keep it simple & conservative — we can refine later
                # owner inference: widen the search window and check segment membership
        owner = "UNKNOWN"
        # consider ALL string segments for exact membership checks
        segs = {str(p) for p in path if isinstance(p, str)}
        if ";l5" in segs:
            owner = "SUIT"
        elif "P;m" in segs:
            owner = "SHIP"
        elif "<IP" in segs:
            owner = "FREIGHTER"
        elif "3Nc" in segs:
            owner = "STORAGE"
        elif "8ZP" in segs:
            owner = "VEHICLE"
        else:
            # fallback: scan a much larger tail of the path for the legacy dotted patterns
            pstr = ".".join(str(p) for p in path[-256:])
            if ".;l5." in pstr:
                owner = "SUIT"
            elif ".P;m." in pstr:
                owner = "SHIP"
            elif ".<IP." in pstr:
                owner = "FREIGHTER"
            elif ".3Nc." in pstr:
                owner = "STORAGE"
            elif ".8ZP." in pstr:
                owner = "VEHICLE"
            


        if owner == "FREIGHTER": owner = "FRIGATE"
        container = path_signature(path)
        # Propagate known owner per container (stabilizes UNKNOWN bins)
        prev = container_owner.get(container)
        if owner == "UNKNOWN" and prev:
            owner = prev
        elif owner != "UNKNOWN":
            container_owner[container] = owner


        totals[rid] += amt

        if args.out_slots:
            # Derive a slot index from last numeric segment in path
            slot_index = None
            for seg in reversed(path):
                if isinstance(seg, int):
                    slot_index = seg
                    break
            # If slot_index is still None or negative, assign a stable per-container sequence
            if slot_index is None or (isinstance(slot_index, int) and slot_index < 0):
                auto_slot_counter[container] += 1
                slot_index = auto_slot_counter[container]

            # --- begin: heuristic owner/inventory inference (NMS-Inventory) ---
            # Derive owner by path keywords if still unknown.
            pstr = ".".join(str(p) for p in path)  # ensure defined regardless of earlier branches
            p_low = pstr.lower()

            def _has(*keys):
                return any(k in p_low for k in keys)


            # Owner inference
            if owner == "UNKNOWN":
                if _has("suit", "playerinventory", "playerstate", "inventory.suit"):
                    owner = "SUIT"
                elif _has("ship", "currentship", "shipinventory", "inventory.ship"):
                    owner = "SHIP"
                elif _has("freighter", "frigate", "capitalship", "inventory.freighter"):
                    owner = "FRIGATE"
                elif _has("vehicle", "exocraft", "buggy", "roamer", "nomad", "colossus", "minotaur", "nautilon"):
                    owner = "VEHICLE"
                elif _has("storage", "chest", "base", "homebase", "storagecontainer"):
                    owner = "STORAGE"

            # Inventory type inference
            # Prefer explicit slot hint when available
            inv_hint = (dict_get(obj, "InventoryType", "") or "").upper()
            if not inv_hint:
                if _has("tech"):
                    inv_hint = "TECHONLY"
                elif _has("cargo"):
                    inv_hint = "CARGO"

            if inv_hint in ("TECH", "TECHNOLOGY"):
                inv_hint = "TECHONLY"

            if inv_hint in ("TECHONLY", "CARGO", "GENERAL"):
                if inv == "GENERAL" and inv_hint != "GENERAL":
                    inv = inv_hint

            # Normalize freighter wording
            if owner == "FREIGHTER":
                owner = "FRIGATE"
            # --- end: heuristic owner/inventory inference (NMS-Inventory) ---
            # Final fallback: if still UNKNOWN and looks like a personal inventory page, call it SUIT
            if owner == "UNKNOWN" and inv == "GENERAL" and not _has(
                "storage","storagecontainer","homebase",
                "freighter","frigate","capitalship",
                "ship","vehicle","exocraft","roamer","nomad","colossus","minotaur","nautilon"
            ):
                owner = "SUIT"


            slots_rows.append({
                "owner_type": owner,
                "inventory": inv,
                "container_id": container,
                "slot_index": slot_index if slot_index is not None else -1,
                "resource_id": rid,
                "amount": amt,
            })

    # write totals
    os.makedirs(os.path.dirname(args.out_totals), exist_ok=True)
    with open(args.out_totals, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["resource_id", "total_amount"])
        for rid, amt in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0])):
            w.writerow([rid, amt])

    # write slots if requested
    if args.out_slots:
        os.makedirs(os.path.dirname(args.out_slots), exist_ok=True)
        with open(args.out_slots, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["owner_type","inventory","container_id","slot_index","resource_id","amount"])
            w.writeheader()
            for row in slots_rows:
                w.writerow(row)

    # human-friendly summary to stdout
    print("Top totals:")
    for rid, amt in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:20]:
        print(f"  {rid:>14}  {amt}")

if __name__ == "__main__":
    import os
    sys.exit(main())
