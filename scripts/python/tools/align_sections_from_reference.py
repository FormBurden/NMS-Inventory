from __future__ import annotations
import argparse, json, os
from typing import Any, Dict, List, Tuple
from scripts.python.utils.json_tools import load_json, save_json, ensure_dir
from scripts.python.utils.paths import walk_with_path, path_to_string

Json = Any

def _fingerprint_array(arr: list) -> Tuple[int, int, int]:
    """Return (length, avg_dict_keys, dict_ratio)."""
    n = len(arr)
    if n == 0: return (0,0,0)
    dicts = [x for x in arr if isinstance(x, dict)]
    dict_ratio = int(100 * len(dicts) / n)
    avg_keys = 0
    if dicts:
        avg_keys = sum(len(d.keys()) for d in dicts) // len(dicts)
    return (n, avg_keys, dict_ratio)

def _collect_arrays(obj: Json) -> Dict[str, Tuple[int,int,int]]:
    out: Dict[str, Tuple[int,int,int]] = {}
    for (path, val) in walk_with_path(obj):
        if isinstance(val, list) and val:
            fp = _fingerprint_array(val)
            if fp[0] >= 5:  # ignore tiny arrays
                out[path_to_string(path)] = fp
    return out

def _pick_top_candidates(ref_fp: Tuple[int,int,int], ours: Dict[str, Tuple[int,int,int]], max_k=5) -> List[str]:
    # simple L1 distance on tuple
    scored = []
    for p, fp in ours.items():
        dist = sum(abs(a-b) for a,b in zip(ref_fp, fp))
        scored.append((dist, p))
    scored.sort(key=lambda x: x[0])
    return [p for _,p in scored[:max_k]]

def main():
    ap = argparse.ArgumentParser(description="Align large sections (arrays) from NMSSE reference to our JSON by shape.")
    ap.add_argument('--ours', required=True, help='Our decoded JSON (storage/decoded/*.json)')
    ap.add_argument('--ref',  required=True, help='NMSSE JSON reference for the SAME slot')
    ap.add_argument('--out',  default='data/mappings/sections_map.json', help='Output mapping JSON')
    args = ap.parse_args()

    ours = load_json(args.ours)
    ref  = load_json(args.ref)

    arrays_ours = _collect_arrays(ours)
    arrays_ref  = _collect_arrays(ref)

    # choose "interesting" reference arrays by common section names
    want = ["Slots", "Milestone", "Journey", "Teleport", "Teleporter", "Base", "Companion", "Pet", "Creature", "Inventory"]
    ref_targets: Dict[str, List[str]] = {}
    for p in arrays_ref.keys():
        low = p.lower()
        if any(w.lower() in low for w in want):
            ref_targets.setdefault(p, []).append(p)

    # compute candidate matches for each reference array path
    proposals: Dict[str, List[str]] = {}
    for p_ref in ref_targets.keys():
        fp = arrays_ref[p_ref]
        proposals[p_ref] = _pick_top_candidates(fp, arrays_ours, max_k=5)

    # reduce proposals into section labels -> our paths
    # crude labeling: collapse by ref keywords
    labeled: Dict[str, List[str]] = {
        "inventories": [],
        "milestones": [],
        "bases": [],
        "teleporter_history": [],
        "companions": [],
    }

    def label_of(ref_path: str) -> str:
        l = ref_path.lower()
        if "teleport" in l: return "teleporter_history"
        if "milestone" in l or "journey" in l: return "milestones"
        if ".base" in l or l.endswith(".bases") or "bases[" in l or "base[" in l: return "bases"
        if "companion" in l or "pet" in l or "creature" in l: return "companions"
        return "inventories"

    for p_ref, candidates in proposals.items():
        lab = label_of(p_ref)
        for cand in candidates:
            if cand not in labeled[lab]:
                labeled[lab].append(cand)

    # merge into existing out
    existing: Dict[str, List[str]] = {}
    if os.path.isfile(args.out):
        try:
            existing = load_json(args.out)
        except Exception:
            existing = {}

    for k, paths in labeled.items():
        existing.setdefault(k, [])
        for p in paths:
            if p not in existing[k]:
                existing[k].append(p)

    ensure_dir(args.out)
    save_json(args.out, existing, pretty=True)
    print(f"[ok] wrote/updated sections map at {args.out}")
if __name__ == '__main__':
    main()
