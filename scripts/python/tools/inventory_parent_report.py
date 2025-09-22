from __future__ import annotations
import argparse, json, os, sys
from typing import Any, Dict, List, Tuple, Union

# lightweight path helpers to avoid extra imports
Json = Any
Path = Tuple[Union[str,int], ...]

def parse_path_string(s: str) -> Path:
    parts: List[Union[str,int]] = []
    tokens: List[str] = []
    cur = ""; esc = False
    for ch in s:
        if ch == "\\":
            esc = not esc; cur += ch; continue
        if ch == "." and not esc:
            tokens.append(cur); cur = ""
        else:
            cur += ch
        esc = False
    if cur: tokens.append(cur)
    for tok in tokens:
        if tok.endswith("]") and "[" in tok:
            base, idx = tok.rsplit("[", 1)
            base = base.replace("\\.", ".")
            if base: parts.append(base)
            parts.append(int(idx[:-1]))
        else:
            parts.append(tok.replace("\\.", "."))
    return tuple(parts)  # type: ignore

def get_at_path(obj: Json, path: Path) -> Any:
    cur = obj
    for p in path:
        if isinstance(cur, dict) and isinstance(p, str):
            cur = cur.get(p)
        elif isinstance(cur, list) and isinstance(p, int) and 0 <= p < len(cur):
            cur = cur[p]
        else:
            return None
    return cur

def parent_of(path_str: str) -> str:
    toks: List[str] = []
    cur = ""; esc = False
    for ch in path_str:
        if ch == "\\":
            esc = not esc; cur += ch; continue
        if ch == "." and not esc:
            toks.append(cur); cur = ""
        else:
            cur += ch
        esc = False
    if cur: toks.append(cur)
    return ".".join(toks[:-1]) if len(toks) > 1 else (toks[0] if toks else "")

def is_slot_list(node: Any) -> bool:
    return isinstance(node, list) and node and all(isinstance(x, dict) for x in node)

def short_keys(d: Dict[str, Any], kmax: int = 8) -> str:
    if not isinstance(d, dict): return ""
    ks = list(d.keys())[:kmax]
    return ",".join(ks)

def analyze_one(full_json_path: str, out_tsv_path: str, out_json_path: str) -> None:
    with open(full_json_path, "r", encoding="utf-8", errors="ignore") as fh:
        doc = json.load(fh)

    inv_paths: List[str] = (doc.get("_index", {}) or {}).get("inventories") or []
    by_parent: Dict[str, List[str]] = {}
    for s in inv_paths:
        p = parent_of(s)
        if p: by_parent.setdefault(p, []).append(s)

    rows: List[Dict[str, Any]] = []
    for parent, children in by_parent.items():
        slot_arrays = []
        lengths = []
        sample_keys = []
        for s in children:
            node = get_at_path(doc, parse_path_string(s))
            if is_slot_list(node):
                slot_arrays.append(s)
                lengths.append(len(node))
                # capture keys from first slot to help fingerprint container
                if node:
                    sample_keys.append(short_keys(node[0]))
        total_slots = sum(lengths)
        parent_node = get_at_path(doc, parse_path_string(parent))
        parent_keys = short_keys(parent_node if isinstance(parent_node, dict) else {}, 12)
        rows.append({
            "parent": parent,
            "child_count": len(children),
            "slot_arrays": slot_arrays,
            "slot_lengths": lengths,
            "total_slots": total_slots,
            "parent_keys": parent_keys,
            "sample_slot_keys": list({k for k in sample_keys if k}),
        })

    # write TSV (human-friendly)
    with open(out_tsv_path, "w", encoding="utf-8", newline="") as fh:
        fh.write("parent\tchild_count\tslot_lengths\ttotal_slots\tparent_keys\tsample_slot_keys\n")
        for r in rows:
            fh.write(
                f"{r['parent']}\t{r['child_count']}\t"
                f"{','.join(map(str,r['slot_lengths']))}\t{r['total_slots']}\t"
                f"{r['parent_keys']}\t{';'.join(r['sample_slot_keys'])}\n"
            )

    # write JSON (machine-friendly, if we want to post-process)
    with open(out_json_path, "w", encoding="utf-8", newline="") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)

    print(f"[ok] wrote {out_tsv_path} and {out_json_path} ({len(rows)} parents)")

def main():
    ap = argparse.ArgumentParser(description="Dump inventory parent groups from full-parse files.")
    ap.add_argument("inputs", nargs="+", help="Paths to output/fullparse/*.full.json")
    args = ap.parse_args()

    os.makedirs("output/reports", exist_ok=True)
    for p in args.inputs:
        stem = os.path.basename(p).replace(".full.json","")
        tsv = os.path.join("output/reports", f"inventory_parents_{stem}.tsv")
        jsn = os.path.join("output/reports", f"inventory_parents_{stem}.json")
        analyze_one(p, tsv, jsn)

if __name__ == "__main__":
    main()
