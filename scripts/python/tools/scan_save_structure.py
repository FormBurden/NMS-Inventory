#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scan a decoded No Man's Sky save JSON and summarize its structure.

Outputs (to output/scan/ by default):
  - <basename>.scan.paths.json      : path -> counts by type
  - <basename>.scan.arrays.json     : array path -> length histogram + samples
  - <basename>.scan.keywords.json   : paths that match interesting keywords (with 1-sample preview)

Usage:
  python3 scripts/python/tools/scan_save_structure.py --full storage/decoded/savenormal.json

Optional:
  --outdir output/scan
  --max-samples 1
"""

import argparse, json, os, sys
from collections import defaultdict
from typing import Any, Dict, List, Tuple

def _extract_first_json_value(s: str) -> str | None:
    """Return substring of the FIRST complete top-level JSON value in s, or None."""
    i = 0
    n = len(s)
    # skip BOM and leading whitespace/NULs
    if n and s[0] == "\ufeff":
        i = 1
    while i < n and s[i] in " \t\r\n\x00":
        i += 1
    if i >= n:
        return None
    start = i
    opening = s[i]
    if opening not in "[{":
        # Not an object/array — try to find next plausible start
        while i < n and s[i] not in "[{":
            i += 1
        if i >= n:
            return None
        start = i
        opening = s[i]
    # Walk to matching close, being careful with strings/escapes.
    depth = 0
    in_str = False
    esc = False
    for j in range(start, n):
        ch = s[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        # not in string
        if ch == '"':
            in_str = True
            continue
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                # include this closing bracket
                return s[start:j+1]
        # other characters just pass
    return None

def load_json_relaxed(path: str) -> Any:
    """Load JSON, tolerating concatenated docs or trailing bytes by extracting the first top-level value."""
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        raw = fh.read()
    # strip trailing NULs/whitespace
    raw = raw.rstrip("\x00 \t\r\n")
    # First try normal parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Try extracting first complete JSON value
    first = _extract_first_json_value(raw)
    if first is not None:
        return json.loads(first)
    # Last resort: try first non-empty line that looks like JSON
    for line in raw.splitlines():
        t = line.strip()
        if t and t[0] in "[{":
            try:
                return json.loads(t)
            except Exception:
                continue
    # Give up
    raise

def ensure_dir(d: str) -> None:
    os.makedirs(d, exist_ok=True)

def short_preview(v: Any, limit: int = 160) -> Any:
    try:
        s = json.dumps(v, ensure_ascii=False)
    except Exception:
        s = str(v)
    if len(s) > limit:
        s = s[:limit] + "…"
    return s

def walk(obj: Any, path: str, paths_count: Dict[str, Dict[str,int]],
         arrays: Dict[str, Dict[str,Any]], kw_hits: Dict[str, List[Dict[str,Any]]],
         keywords: List[str], max_samples: int) -> None:
    t = type(obj).__name__
    # Type tallies per path
    bucket = paths_count[path]
    bucket[t] = bucket.get(t, 0) + 1

    # Keyword hits (record once per path with a small preview)
    low = path.lower()
    if any(k in low for k in keywords):
        arr = kw_hits[path]
        if len(arr) < max_samples:
            sample = obj[0] if isinstance(obj, list) and obj else obj
            arr.append({"type": t, "preview": short_preview(sample)})

    # Recurse
    if isinstance(obj, dict):
        for k, v in obj.items():
            nxt = f"{path}.{k}" if path else k
            walk(v, nxt, paths_count, arrays, kw_hits, keywords, max_samples)
    elif isinstance(obj, list):
        ah = arrays[path]
        ah.setdefault("len_hist", defaultdict(int))
        ah["len_hist"][len(obj)] += 1
        if "samples" not in ah:
            ah["samples"] = []
        if obj and len(ah["samples"]) < max_samples:
            ah["samples"].append(short_preview(obj[0]))
        # descend into a few elements to learn structure
        limit = min(len(obj), 3)
        for i in range(limit):
            walk(obj[i], f"{path}[{i}]", paths_count, arrays, kw_hits, keywords, max_samples)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", required=True, help="Path to decoded save JSON (e.g., storage/decoded/savenormal.json)")
    ap.add_argument("--outdir", default="output/scan", help="Directory for outputs")
    ap.add_argument("--max-samples", type=int, default=1, help="Preview samples per matching path")
    args = ap.parse_args()

    src = args.full
    if not os.path.exists(src):
        print(f"Missing file: {src}", file=sys.stderr)
        sys.exit(2)

    ensure_dir(args.outdir)
    base = os.path.splitext(os.path.basename(src))[0]

    # <<< tolerant loader
    data = load_json_relaxed(src)

    paths_count: Dict[str, Dict[str,int]] = defaultdict(dict)
    arrays: Dict[str, Dict[str,Any]] = defaultdict(dict)
    kw_hits: Dict[str, List[Dict[str,Any]]] = defaultdict(list)

    keywords = [
        # assets
        "ship", "freighter", "multitool", "multi_tool", "tool", "exocraft", "vehicle", "mech",
        # bases/teleport
        "base", "bases", "teleport", "teleporter",
        # missions
        "mission", "objectives", "quest",
        # inventory/slots/tech
        "inventory", "slots", "width", "height", "grid", "technology", "tech", "installed",
        # currencies/resources
        "units", "nanite", "quicksilver", "currency", "currencies", "resource", "product",
        # names/ids
        "name", "system", "planet", "id", "seed",
    ]

    walk(data, "", paths_count, arrays, kw_hits, keywords, args.max_samples)

    # Normalize arrays histogram dicts to lists for stable JSON
    arrays_out = {}
    for p, info in arrays.items():
        hist = info.get("len_hist", {})
        arrays_out[p or "$"] = {
            "len_hist": sorted([(int(k), int(v)) for k,v in hist.items()], key=lambda x: x[0]),
            "samples": info.get("samples", []),
        }

    # Sort outputs for readability
    paths_out = []
    for p, types in paths_count.items():
        paths_out.append({
            "path": p or "$",
            "types": {k:int(v) for k,v in sorted(types.items())}
        })
    paths_out.sort(key=lambda x: x["path"])

    kw_out = []
    for p, arr in kw_hits.items():
        kw_out.append({
            "path": p or "$",
            "hits": arr
        })
    # prioritize deeper, keyword-rich paths
    kw_out.sort(key=lambda x: (x["path"].count("."), x["path"]))

    out_paths = os.path.join(args.outdir, f"{base}.scan.paths.json")
    out_arrays = os.path.join(args.outdir, f"{base}.scan.arrays.json")
    out_kw = os.path.join(args.outdir, f"{base}.scan.keywords.json")

    with open(out_paths, "w", encoding="utf-8") as fh:
        json.dump(paths_out, fh, ensure_ascii=False)
    with open(out_arrays, "w", encoding="utf-8") as fh:
        json.dump(arrays_out, fh, ensure_ascii=False)
    with open(out_kw, "w", encoding="utf-8") as fh:
        json.dump(kw_out, fh, ensure_ascii=False)

    print(f"[scan] wrote {out_paths}")
    print(f"[scan] wrote {out_arrays}")
    print(f"[scan] wrote {out_kw}")

if __name__ == "__main__":
    main()
