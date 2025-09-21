#!/usr/bin/env python3
import argparse, json, sys, os
from collections import defaultdict, deque

def load_json(path):
    with open(path, "rb") as f:
        # file is UTF-8 JSON now
        return json.loads(f.read().decode("utf-8"))

def walk(obj):
    """Yield (path_list, parent, key, value) for every primitive value."""
    stack = deque([([], None, None, obj)])
    while stack:
        path, parent, key, val = stack.pop()
        if isinstance(val, dict):
            for k, v in val.items():
                stack.append((path+[k], val, k, v))
        elif isinstance(val, list):
            for i, v in enumerate(val):
                stack.append((path+[i], val, i, v))
        else:
            yield (path, parent, key, val)

def is_candidate_id(v):
    return isinstance(v, str) and v.startswith("^") and v.isascii()

def numeric_fields(d):
    return {k:v for k,v in d.items() if isinstance(v, int)}

def show_parent(parent, highlight_key=None, maxlen=200):
    try:
        import math
        # pretty compact one-line dump of a dict parent
        pairs = []
        for k,v in parent.items():
            sv = repr(v)
            if len(sv) > maxlen: sv = sv[:maxlen]+"…"
            if k == highlight_key: k=f"*{k}*"
            pairs.append(f"{k}={sv}")
        return "{ " + ", ".join(pairs) + " }"
    except Exception:
        return repr(parent)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True, help="Decoded save JSON")
    ap.add_argument("--ids", required=True, help="Comma-separated list, e.g. ^ANTIMATTER,^LAUNCHSUB,^LAND2")
    ap.add_argument("--limit", type=int, default=50, help="Max matches per ID to print")
    args = ap.parse_args()

    want = [s.strip() for s in args.ids.split(",") if s.strip()]
    data = load_json(args.json)

    matches = defaultdict(list)
    for path, parent, key, val in walk(data):
        if is_candidate_id(val) and val in want and isinstance(parent, dict):
            matches[val].append((path, parent, key))

    totals = {}
    for rid in want:
        rows = matches.get(rid, [])
        print(f"\n=== {rid} : {len(rows)} matches ===")
        taken = 0
        total_est = 0
        for path, parent, key in rows:
            nums = numeric_fields(parent)
            # Heuristic: "amount" is usually the largest small-ish int in the same object
            # (ignore huge counters like 100000/160000)
            cand = [v for v in nums.values() if 0 < v < 50000]
            guess = max(cand) if cand else 0
            total_est += guess
            if taken < args.limit:
                pstr = ".".join(str(p) for p in path[-8:])  # tail of path for context
                print(f"- path_tail: {pstr}")
                print(f"  parent_keys: {list(parent.keys())}")
                print(f"  numeric_siblings: {nums}")
                print(f"  guess_amount: {guess}")
                print(f"  parent: {show_parent(parent, highlight_key=key)}")
            taken += 1
        totals[rid] = total_est
        print(f"==> heuristic_total({rid}) ≈ {total_est}")

    print("\nSUMMARY (heuristic totals):")
    for rid, tot in totals.items():
        print(f"  {rid}: {tot}")

if __name__ == "__main__":
    sys.exit(main())
