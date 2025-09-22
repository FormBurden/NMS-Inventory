#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Entry point for augmenting fullparse files with inventory rollups.
Usage:
  python3 scripts/python/tools/augment_fullparse_rollup.py --all
  python3 scripts/python/tools/augment_fullparse_rollup.py --full output/fullparse/savenormal.full.json --decoded storage/decoded/savenormal.json --in-place
"""
import argparse, os, sys

# Ensure 'scripts/python' is importable when running as a script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PY_ROOT = os.path.dirname(SCRIPT_DIR)
if PY_ROOT not in sys.path:
    sys.path.insert(0, PY_ROOT)

from augment.augmenter import augment_one
from augment.io_utils import find_pairs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.', help='repo root for output/ and storage/')
    ap.add_argument('--full')
    ap.add_argument('--decoded')
    ap.add_argument('--in-place', action='store_true')
    ap.add_argument('--all', action='store_true')
    args = ap.parse_args()

    if args.all:
        pairs = find_pairs(args.root)
        if not pairs:
            print(f"No pairs found under --root {args.root}", file=sys.stderr)
            sys.exit(2)
        for full_path, dec_path in pairs:
            out = augment_one(full_path, dec_path, in_place=True)
            print(f"[augmented] {out}")
        return

    if not args.full or not args.decoded:
        print("Need --full and --decoded, or use --all", file=sys.stderr); sys.exit(2)
    if not os.path.exists(args.full):   print(f"Missing --full {args.full}", file=sys.stderr); sys.exit(2)
    if not os.path.exists(args.decoded):print(f"Missing --decoded {args.decoded}", file=sys.stderr); sys.exit(2)

    out = augment_one(args.full, args.decoded, in_place=args.in_place)
    print(out)

if __name__ == '__main__':
    main()
