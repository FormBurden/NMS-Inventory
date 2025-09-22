#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extract sample structures for ships, multitools, exocraft, freighter, teleport entries
from a decoded NMS save with obfuscated keys. Produces a single JSON with paths, lengths,
first-element keys, and flattened key previews so we can map fields robustly.

Usage:
  python3 scripts/python/tools/extract_asset_samples.py \
    --decoded storage/decoded/savenormal.json \
    --out output/deepdebug/savenormal.assets.samples.json
"""
import argparse, json, os, re, sys
from typing import Any, Dict, List, Tuple

# ---------- tolerant JSON loader (handles trailing bytes / concatenated docs) ----------
def load_json_relaxed(path: str) -> Any:
    s = open(path, "r", encoding="utf-8", errors="ignore").read()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    i, n = 0, len(s)
    if n and s[0] == "\ufeff":
        i = 1
    while i < n and s[i] not in "[{":
        i += 1
    if i >= n:
        raise
    start, depth, ins, esc = i, 0, False, False
    for j in range(i, n):
        ch = s[j]
        if ins:
            if esc: esc = False
            elif ch == "\\": esc = True
            elif ch == '"':  ins = False
            continue
        if ch == '"':
            ins = True; continue
        if ch in "[{": depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                frag = s[start:j+1]
                return json.loads(frag)
    for line in s.splitlines():
        t = line.strip()
        if t and t[0] in "[{":
            try: return json.loads(t)
            except Exception: pass
    raise

# ---------- helpers ----------
def preview(v: Any, limit: int = 200) -> Any:
    try:
        s = json.dumps(v, ensure_ascii=False)
    except Exception:
        s = str(v)
    if len(s) > limit:
        s = s[:limit] + "…"
    return s

def flat_keys(d: Any, max_depth: int = 2, prefix: str = "") -> List[str]:
    out: List[str] = []
    if max_depth < 0: return out
    if isinstance(d, dict):
        for k, v in d.items():
            p = f"{prefix}.{k}" if prefix else k
            out.append(p)
            if max_depth:
                out.extend(flat_keys(v, max_depth - 1, p))
    elif isinstance(d, list):
        if d:
            p = f"{prefix}[0]" if prefix else "[0]"
            out.append(p)
            if max_depth:
                out.extend(flat_keys(d[0], max_depth - 1, p))
    return out

def any_str_matches(x: Any, rx: re.Pattern, limit: int = 1) -> bool:
    found = 0
    def walk(n):
        nonlocal found
        if found >= limit: return
        if isinstance(n, dict):
            for v in n.values(): walk(v)
        elif isinstance(n, list):
            for v in n[:8]: walk(v)
        elif isinstance(n, str):
            if rx.search(n): found += 1
    walk(x); return found > 0

def walk_collect_arrays(root: Any) -> List[Tuple[str, list]]:
    out: List[Tuple[str, list]] = []
    def walk(n, p: str):
        if isinstance(n, dict):
            for k, v in n.items():
                walk(v, f"{p}.{k}" if p else k)
        elif isinstance(n, list):
            out.append((p, n))
            for i, v in enumerate(n[:6]):
                walk(v, f"{p}[{i}]")
    walk(root, "")
    return out

def walk_collect_objects(root: Any) -> List[Tuple[str, dict]]:
    out: List[Tuple[str, dict]] = []
    def walk(n, p: str):
        if isinstance(n, dict):
            out.append((p, n))
            for k, v in n.items():
                walk(v, f"{p}.{k}" if p else k)
        elif isinstance(n, list):
            for i, v in enumerate(n[:6]):
                walk(v, f"{p}[{i}]")
    walk(root, "")
    return out

# scoring prefers small “assets list” arrays (<=12), with dict elements containing strings
def score_asset_array(path: str, arr: list, hint_rx: re.Pattern) -> int:
    s = 0
    if len(arr) and all(isinstance(e, dict) for e in arr): s += 2
    if 1 <= len(arr) <= 12: s += 3
    if any_str_matches(arr, hint_rx, 1): s += 5
    # de-prioritize huge arrays like 96-slot inventories
    if len(arr) > 40: s -= 3
    return s

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decoded", required=True)
    ap.add_argument("--out", required=True, help="Output JSON path (e.g., output/deepdebug/savenormal.assets.samples.json)")
    args = ap.parse_args()

    save = load_json_relaxed(args.decoded)

    ships_rx = re.compile(r"\b(PlayerShipBase|Starship Inventory Slot|Starship)\b", re.I)
    mtool_rx = re.compile(r"(MULTITOOL\.SCENE|Multi-Tool Inventory Slot|Multi.?Tool)", re.I)
    exo_rx   = re.compile(r"\b(Exocraft|Vehicle|Nomad|Roamer|Colossus|Minotaur|Mech)\b", re.I)
    fr_rx    = re.compile(r"\b(Freighter|FreighterBase|FreighterCargo)\b", re.I)
    tp_rx    = re.compile(r"\b(teleport|teleporter|portal|recent destinations?)\b", re.I)

    arrays = walk_collect_arrays(save)
    objs   = walk_collect_objects(save)

    def best_array(rx: re.Pattern):
        scored = [ (score_asset_array(p,a,rx), p, a) for (p,a) in arrays if any_str_matches(a,rx,1) ]
        if not scored: return None
        scored.sort(key=lambda t: (t[0], -len(t[2])), reverse=True)
        return scored[0]  # (score, path, arr)

    def first_object(rx: re.Pattern):
        for p,o in objs:
            if any_str_matches(o, rx, 1):
                return (p,o)
        return None

    out: Dict[str, Any] = {}
    for label, rx in (("ships",ships_rx), ("multitools",mtool_rx), ("exocraft",exo_rx)):
        pick = best_array(rx)
        if pick:
            _score, p, arr = pick
            first = arr[0] if arr and isinstance(arr[0], dict) else None
            out[label] = {
                "path": p, "length": len(arr),
                "first_keys": sorted(list(first.keys())) if isinstance(first, dict) else [],
                "flat_keys": flat_keys(first, 2) if isinstance(first, dict) else [],
                "first_preview": preview(first) if first is not None else None
            }

    fr = first_object(fr_rx)
    if fr:
        p,o = fr
        out["freighter"] = {
            "path": p,
            "first_keys": sorted(list(o.keys())),
            "flat_keys": flat_keys(o, 2),
            "first_preview": preview(o) if o is not None else None
        }

    tp = best_array(tp_rx)
    if tp:
        _s, p, arr = tp
        first = arr[0] if arr and isinstance(arr[0], dict) else None
        out["teleport"] = {
            "path": p, "length": len(arr),
            "first_keys": sorted(list(first.keys())) if isinstance(first, dict) else [],
            "flat_keys": flat_keys(first, 2) if isinstance(first, dict) else [],
            "first_preview": preview(first) if first is not None else None
        }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"[samples] wrote {args.out}")

if __name__ == "__main__":
    main()
