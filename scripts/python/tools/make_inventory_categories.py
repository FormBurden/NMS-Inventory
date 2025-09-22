from __future__ import annotations
import argparse, json, os, sys
from typing import Any, Dict, List

def main():
    ap = argparse.ArgumentParser(description="Make starter inventory_categories.json from inventory_parents_*.json reports.")
    ap.add_argument("reports", nargs="+", help="output/reports/inventory_parents_*.json")
    ap.add_argument("-o","--out", default="data/mappings/inventory_categories.json", help="output mapping file")
    args = ap.parse_args()

    parents: Dict[str, str] = {}
    for rp in args.reports:
        try:
            with open(rp, "r", encoding="utf-8", errors="ignore") as fh:
                rows = json.load(fh)
        except Exception as e:
            print(f"[warn] skip {rp}: {e}", file=sys.stderr)
            continue
        for r in rows:
            p = r.get("parent")
            lens = r.get("slot_lengths") or []
            if not p or not lens:
                continue
            # only keep parents that actually had slot arrays
            parents.setdefault(p, "Storage")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="") as fh:
        json.dump(parents, fh, ensure_ascii=False, indent=2)
    print(f"[ok] wrote {args.out} with {len(parents)} parents")

if __name__ == "__main__":
    main()
