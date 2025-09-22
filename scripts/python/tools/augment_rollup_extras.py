#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Augment existing fullparse rollups with extra, derived sections.

Usage:
  # Enrich all files in output/fullparse
  python3 scripts/python/tools/augment_rollup_extras.py --all --in-place

  # Or enrich one file (optionally write to a separate path)
  python3 scripts/python/tools/augment_rollup_extras.py \
    --full output/fullparse/savenormal.full.json --in-place
"""
import argparse, json, os, sys, glob
from typing import Dict, Any, Iterable, Tuple

def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        return json.load(fh)

def save_json(path: str, data: Dict[str, Any]) -> None:
    # Preserve compactness but be deterministic
    with open(path, "w", encoding="utf-8", newline="") as fh:
        json.dump(data, fh, ensure_ascii=False)

def as_total(v: Any) -> int:
    """
    Accepts either a bare number or an object with {"total": <int>}.
    Returns an int (defaults to 0).
    """
    if isinstance(v, (int, float)):
        try:
            return int(v)
        except Exception:
            return 0
    if isinstance(v, dict):
        t = v.get("total", 0)
        try:
            return int(t)
        except Exception:
            return 0
    return 0

def compute_owner_category_share(by_owner_by_category: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    For each owner, compute totals + percent split for general/tech/cargo.
    Emits:
      owner_category_share = {
        "<owner>": {
            "totals": {"general": int, "tech": int, "cargo": int, "total": int},
            "pct":    {"general": float, "tech": float, "cargo": float}
        }, ...
      }
    """
    out: Dict[str, Dict[str, Any]] = {}
    for owner, cats in (by_owner_by_category or {}).items():
        g = as_total(cats.get("general", 0))
        t = as_total(cats.get("tech", 0))
        c = as_total(cats.get("cargo", 0))
        S = as_total(cats.get("total", (g + t + c)))
        def pct(x: int, denom: int) -> float:
            return (float(x) * 100.0 / float(denom)) if denom else 0.0
        out[owner] = {
            "totals": {"general": g, "tech": t, "cargo": c, "total": S},
            "pct": {"general": pct(g, S), "tech": pct(t, S), "cargo": pct(c, S)},
        }
    return out

def aggregate_code_totals_from_top(by_owner_top_items: Dict[str, Any]) -> Dict[str, int]:
    """
    Build a global code → total_count map by summing across owners’ top lists.
    Only uses the provided top lists (it does not scan *all* items).
    """
    totals: Dict[str, int] = {}
    for owner, arr in (by_owner_top_items or {}).items():
        if not isinstance(arr, list):
            continue
        for e in arr:
            if not isinstance(e, dict): 
                continue
            code = e.get("code")
            cnt  = e.get("count", 0)
            if not code:
                continue
            try:
                cnt = int(cnt)
            except Exception:
                cnt = 0
            totals[code] = totals.get(code, 0) + cnt
    return totals

def build_owner_code_union_top(by_owner_top_items: Dict[str, Any]) -> Dict[str, Any]:
    """
    For each owner, gather the set of codes present in their top list,
    sorted by (count desc, code asc) for determinism.
    Emits:
      { "<owner>": [{"code": str, "count": int}] }
    """
    out: Dict[str, Any] = {}
    for owner, arr in (by_owner_top_items or {}).items():
        if not isinstance(arr, list):
            continue
        # Merge duplicates in case the list wasn't unique
        acc: Dict[str, int] = {}
        for e in arr:
            if not isinstance(e, dict): 
                continue
            code = e.get("code")
            cnt  = e.get("count", 0)
            if not code:
                continue
            try:
                cnt = int(cnt)
            except Exception:
                cnt = 0
            acc[code] = max(acc.get(code, 0), cnt)
        # sort: count desc, code asc
        out[owner] = [{"code": k, "count": acc[k]} for k in sorted(acc.keys(), key=lambda z: (-acc[z], z))]
    return out

def enrich_one(full_path: str, in_place: bool = True, out_path: str = None) -> str:
    doc = load_json(full_path)
    r = doc.setdefault("_rollup", {})
    inv = r.setdefault("inventory", {})
    by_own_cat = (inv.get("by_owner_by_category") or {})
    by_own_top = (inv.get("by_owner_top_items") or {})

    extras = inv.setdefault("extras", {})
    extras["owner_category_share"] = compute_owner_category_share(by_own_cat)
    extras["code_totals_top"]      = aggregate_code_totals_from_top(by_own_top)
    extras["owner_code_union_top"] = build_owner_code_union_top(by_own_top)

    dst = full_path if in_place or not out_path else out_path
    save_json(dst, doc)
    return dst

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="Process all output/fullparse/*.full.json")
    ap.add_argument("--full", help="Path to a single *.full.json")
    ap.add_argument("--in-place", action="store_true", help="Write back to the same file")
    ap.add_argument("--out", help="When not --in-place, write to this path")
    args = ap.parse_args()

    targets = []
    if args.all:
        targets = sorted(glob.glob(os.path.join("output", "fullparse", "*.full.json")))
        if not targets:
            print("No files matched output/fullparse/*.full.json", file=sys.stderr); sys.exit(2)
    elif args.full:
        if not os.path.exists(args.full):
            print(f"Missing --full {args.full}", file=sys.stderr); sys.exit(2)
        targets = [args.full]
    else:
        print("Need --all or --full", file=sys.stderr); sys.exit(2)

    for f in targets:
        out = enrich_one(f, in_place=args.in_place, out_path=args.out)
        print(f"[enriched] {out}")

if __name__ == "__main__":
    main()
