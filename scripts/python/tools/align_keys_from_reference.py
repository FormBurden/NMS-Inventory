from __future__ import annotations
import argparse, json, os
from collections import Counter, defaultdict
from typing import Any, Dict, Tuple, List
from scripts.python.utils.json_tools import load_json, save_json, flatten_leaves, ensure_dir

def _scalars_index(leaves: List[Tuple[Tuple[str,...], Any]]):
    """Build map: value -> list of paths (only if scalar is 'matchable')."""
    idx = defaultdict(list)
    for path, val in leaves:
        if isinstance(val, (int, float)):
            idx[('num', val)].append(path)
        elif isinstance(val, str):
            s = val.strip()
            if 0 < len(s) <= 128:
                idx[('str', s)].append(path)
        elif isinstance(val, bool):
            idx[('bool', val)].append(path)
        # None is too ambiguous; skip
    return idx

def suggest_mapping(ours: Dict, ref: Dict) -> Dict[str, str]:
    ours_leaves = flatten_leaves(ours)
    ref_leaves  = flatten_leaves(ref)
    idx_ours = _scalars_index(ours_leaves)
    idx_ref  = _scalars_index(ref_leaves)

    # candidate key-name pairs by co-occurring identical leaf values
    votes = Counter()
    for key, our_paths in idx_ours.items():
        ref_paths = idx_ref.get(key)
        if not ref_paths:
            continue
        # only consider unique matches on each side (avoid repeated values)
        if len(our_paths) == 1 and len(ref_paths) == 1:
            our_last = our_paths[0][-1] if our_paths[0] else ''
            ref_last = ref_paths[0][-1] if ref_paths[0] else ''
            if our_last and ref_last and our_last != ref_last:
                votes[(our_last, ref_last)] += 1

    # produce best guess per "our last key"
    best = {}
    for (our_last, ref_last), count in votes.most_common():
        # take first (highest votes) for each our_last
        if our_last not in best:
            best[our_last] = ref_last
    return best

def main():
    ap = argparse.ArgumentParser(description="Suggest key mapping by aligning our decoded save with an NMSSaveEditor JSON.")
    ap.add_argument('--ours', required=True, help='Path to our decoded JSON (e.g., storage/decoded/saveexpedition.json)')
    ap.add_argument('--ref', required=True, help='Path to NMSSaveEditor JSON (e.g., external/NMSSE/save2_same_slot.json)')
    ap.add_argument('--out', default='data/mappings/keys_map.json', help='Where to write/merge the mapping JSON')
    args = ap.parse_args()

    ours = load_json(args.ours)
    ref  = load_json(args.ref)

    proposed = suggest_mapping(ours, ref)

    # merge with existing mapping if present
    mapping = {}
    if os.path.isfile(args.out):
        try:
            mapping = load_json(args.out)
        except Exception:
            mapping = {}

    # keep existing mappings, add new proposals without overwriting
    for k, v in proposed.items():
        mapping.setdefault(k, v)

    ensure_dir(args.out)
    save_json(args.out, mapping, pretty=True)
    print(f"[ok] wrote/updated mapping at {args.out} with {len(proposed)} proposals ({len(mapping)} total keys).")

if __name__ == '__main__':
    main()
