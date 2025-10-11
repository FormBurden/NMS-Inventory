from __future__ import annotations
import argparse, json, os, sys
from typing import Any, Dict
from .utils.json_tools import load_json, save_json, clean_strings, deep_rename_keys, ensure_dir
from .meta.enrich import enrich_meta
from .sections.indexers import find_sections, build_summary, merge_sections_with_map
from .sections.inventory_rollup import compute_inventory_rollup


def main():
    ap = argparse.ArgumentParser(
        description="Full-parse: clean strings, optional rename, enrich meta, index big sections, summarize."
    )
    ap.add_argument('-i','--input', required=True, help='Input decoded JSON from our decoder (save.json/save2.json)')
    ap.add_argument('-o','--out',   required=True, help='Output JSON path')
    ap.add_argument('--mapping',  default='data/mappings/keys_map.json', help='Optional key-rename mapping JSON (ours_key -> readable_key)')
    ap.add_argument('--sections-map', default='data/mappings/sections_map.json', help='Optional sections mapping JSON (labels -> our paths)')
    ap.add_argument('--inv-child-types', default='data/mappings/inventory_child_types.json', help='Optional child-slot path -> {general,tech,cargo}')
    ap.add_argument('--no-rename', action='store_true', help='Do not apply key renames even if mapping exists')
    ap.add_argument('--inv-categories', default='data/mappings/inventory_categories.json', help='Optional parent->category mapping for inventory roll-up')
    args = ap.parse_args()

    data: Any = load_json(args.input)
    data = clean_strings(data)

    if not args.no_rename and os.path.isfile(args.mapping):
        try:
            mapping = load_json(args.mapping)
            if isinstance(mapping, dict) and mapping:
                data = deep_rename_keys(data, mapping)
        except Exception as e:
            print(f"[warn] mapping load failed: {e}", file=sys.stderr)

    meta = enrich_meta(data)
    index = find_sections(data)

    # optional: merge in explicit sections map (improves results on obfuscated keys)
    if os.path.isfile(args.sections_map):
        try:
            sections_map = load_json(args.sections_map)
            if isinstance(sections_map, dict):
                # Use sections_map as source of truth for inventories (prevents false positives)
                mapped_inventories = sections_map.get("inventories") or []
                if mapped_inventories:
                    index["inventories"] = list(dict.fromkeys(mapped_inventories))
                # Union for other sections
                index = merge_sections_with_map(index, sections_map)
        except Exception as e:
            print(f"[warn] sections_map load failed: {e}", file=sys.stderr)



    inv_cats = {}
    if os.path.isfile(args.inv_categories):
        try:
            inv_cats = load_json(args.inv_categories) or {}
        except Exception as e:
            print(f"[warn] inventory_categories load failed: {e}", file=sys.stderr)

    inv_child_types = {}
    if os.path.isfile(args.inv_child_types):
        try:
            inv_child_types = load_json(args.inv_child_types) or {}
        except Exception as e:
            print(f"[warn] inventory_child_types load failed: {e}", file=sys.stderr)


    summary = build_summary(data, index)
    rollup = {"inventory": compute_inventory_rollup(data, index, inv_cats, inv_child_types)}
    summary["inventory"]["containers"] = rollup["inventory"]["totals"]["containers"]
    summary["inventory"]["total_slots"] = rollup["inventory"]["totals"]["total"]
    out = {"_meta": meta, "_index": index, "_summary": summary, "_rollup": rollup, **data} if isinstance(data, dict) else \
        {"_meta": meta, "_index": index, "_summary": summary, "_rollup": rollup, "data": data}

    ensure_dir(args.out)
    save_json(args.out, out, pretty=True)
    print(f"[ok] wrote {args.out}", file=sys.stderr)

if __name__ == '__main__':
    main()
