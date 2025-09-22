#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Augments output/fullparse/*.full.json with extra _rollup data based on storage/decoded/*.json:
  - _rollup.currencies: Units (wGS), Nanites (7QL)  [Quicksilver: TODO]
  - _rollup.inventory.top_items: top JWK codes across all items (vLc.6f=.b69)
Usage:
  python3 scripts/python/tools/augment_fullparse_rollup.py --all
  python3 scripts/python/tools/augment_fullparse_rollup.py --full output/fullparse/savenormal.full.json --decoded storage/decoded/savenormal.json --in-place
"""
import argparse, json, os, sys
from collections import Counter

def read_json_lenient(path):
    with open(path,'rb') as f:
        buf = f.read()
    while buf and buf[-1] in b'\x00\r\n \t':
        buf = buf[:-1]
    try:
        text = buf.decode('utf-8')
    except UnicodeDecodeError:
        text = buf.decode('latin-1')
    return json.loads(text)

def safe_get(d, path, default=None):
    cur = d
    for p in path:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return default
    return cur

def guess_quicksilver(vLc6f):
    # TODO: map Quicksilver key; placeholder returns None (omitted from output)
    return None

def build_augments(decoded_obj):
    vLc6f = safe_get(decoded_obj, ('vLc','6f='), {})
    units   = vLc6f.get('wGS')   # Units
    nanites = vLc6f.get('7QL')   # Nanites
    quick   = guess_quicksilver(vLc6f)

    items = safe_get(decoded_obj, ('vLc','6f=','b69'), [])
    ctr = Counter()
    total_items = 0
    for it in items:
        if isinstance(it, dict):
            code = it.get('JWK')
            if isinstance(code, str):
                ctr[code] += 1
                total_items += 1

    top_items = [{'code': k, 'count': v} for k,v in ctr.most_common(200)]
    return {
        'currencies': {
            **({'Units': units} if isinstance(units,(int,float)) else {}),
            **({'Nanites': nanites} if isinstance(nanites,(int,float)) else {}),
            **({'Quicksilver': quick} if isinstance(quick,(int,float)) else {}),
        },
        'inventory': {
            'top_items': top_items,
            'total_items_flat': total_items,
            'distinct_items': len(ctr),
        }
    }

def load_json(path):
    with open(path,'r',encoding='utf-8') as f:
        return json.load(f)

def save_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp,'w',encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def augment_one(full_path, decoded_path, in_place=False, out_path=None):
    full    = load_json(full_path)
    decoded = read_json_lenient(decoded_path)
    aug = build_augments(decoded)

    full.setdefault('_rollup', {})
    full['_rollup'].setdefault('currencies', {})
    for k,v in aug['currencies'].items():
        full['_rollup']['currencies'][k] = v

    full['_rollup'].setdefault('inventory', {})
    full['_rollup']['inventory']['top_items'] = aug['inventory']['top_items']
    full['_rollup']['inventory']['total_items_flat'] = aug['inventory']['total_items_flat']
    full['_rollup']['inventory']['distinct_items'] = aug['inventory']['distinct_items']

    if in_place:
        save_json(full_path, full)
        return full_path
    else:
        name, ext = os.path.splitext(full_path)
        out_path = out_path or (name + '.aug' + ext)
        save_json(out_path, full)
        return out_path

def find_pairs(root='.'):
    full_dir = os.path.join(root, 'output', 'fullparse')
    dec_dir  = os.path.join(root, 'storage', 'decoded')
    pairs = []
    if not os.path.isdir(full_dir) or not os.path.isdir(dec_dir):
        return pairs
    for fn in os.listdir(full_dir):
        if not fn.endswith('.full.json'): continue
        name = fn.replace('.full.json','')
        full_path = os.path.join(full_dir, fn)
        dec_path  = os.path.join(dec_dir, name + '.json')
        if os.path.exists(dec_path):
            pairs.append((full_path, dec_path))
    return pairs

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
            print("No pairs found under --root", args.root, file=sys.stderr)
            sys.exit(2)
        for full_path, dec_path in pairs:
            out = augment_one(full_path, dec_path, in_place=True)
            print(f"[augmented] {out}")
        return

    if not args.full or not args.decoded:
        print("Need --full and --decoded, or use --all", file=sys.stderr); sys.exit(2)
    if not os.path.exists(args.full):   print("Missing --full", args.full, file=sys.stderr); sys.exit(2)
    if not os.path.exists(args.decoded):print("Missing --decoded", args.decoded, file=sys.stderr); sys.exit(2)

    out = augment_one(args.full, args.decoded, in_place=args.in_place)
    print(out)

if __name__ == '__main__':
    main()
