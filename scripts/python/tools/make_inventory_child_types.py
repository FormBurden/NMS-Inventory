from __future__ import annotations
import argparse, json, os, sys
from typing import Any, Dict, List

def main():
    ap = argparse.ArgumentParser(description="Create/merge data/mappings/inventory_child_types.json from inventory_parents_*.json.")
    ap.add_argument("reports", nargs="+", help="output/reports/inventory_parents_*.json")
    ap.add_argument("-o","--out", default="data/mappings/inventory_child_types.json", help="where to write the mapping")
    args = ap.parse_args()

    mapping: Dict[str, str] = {}
    if os.path.isfile(args.out):
        try:
            with open(args.out, "r", encoding="utf-8") as fh:
                mapping = json.load(fh) or {}
        except Exception as e:
            print(f"[warn] could not load existing {args.out}: {e}", file=sys.stderr)

    for rp in args.reports:
        try:
            with open(rp, "r", encoding="utf-8") as fh:
                rows = json.load(fh)
        except Exception as e:
            print(f"[warn] skip {rp}: {e}", file=sys.stderr)
            continue
        for r in rows:
            slot_arrays = r.get("slot_arrays") or []
            for child in slot_arrays:
                # default everything to 'general' (you can edit tech/cargo later)
                mapping.setdefault(child, "general")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(mapping, fh, ensure_ascii=False, indent=2)
    print(f"[ok] wrote {args.out} with {len(mapping)} child entries")

if __name__ == "__main__":
    main()
