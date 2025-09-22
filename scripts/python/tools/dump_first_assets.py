#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse, json, os
from typing import Any, Dict

def load_json_relaxed(path: str) -> Any:
    import json as _j
    s = open(path,"r",encoding="utf-8",errors="ignore").read()
    try: return _j.loads(s)
    except _j.JSONDecodeError: pass
    i,n=0,len(s)
    if n and s[0]=="\ufeff": i=1
    while i<n and s[i] not in "[{]": i+=1
    if i>=n: raise
    start=i; depth=0; ins=False; esc=False
    for j in range(i,n):
        ch=s[j]
        if ins:
            if esc: esc=False
            elif ch=="\\": esc=True
            elif ch=='"': ins=False
            continue
        if ch=='"': ins=True; continue
        if ch in "[{": depth+=1
        elif ch in "]}":
            depth-=1
            if depth==0:
                return _j.loads(s[start:j+1])
    for line in s.splitlines():
        t=line.strip()
        if t and t[0] in "[{]":
            try: return _j.loads(t)
            except: pass
    raise

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--decoded", required=True)
    ap.add_argument("--samples", required=True)
    ap.add_argument("--outdir",  default="output/deepdebug/firsts")
    args=ap.parse_args()

    data    = load_json_relaxed(args.decoded)
    samples = load_json_relaxed(args.samples)
    os.makedirs(args.outdir, exist_ok=True)

    def get_by_path(o:Any, p:str):
        cur=o
        for seg in p.split("."):
            if not seg: continue
            cur = cur.get(seg, {}) if isinstance(cur,dict) else {}
        return cur

    for label in ("ships","multitools","exocraft"):
        path = (samples.get(label) or {}).get("path")
        if not path: continue
        arr = get_by_path(data, path)
        if isinstance(arr,list) and arr:
            with open(os.path.join(args.outdir, f"{label}.first.json"), "w", encoding="utf-8") as fh:
                json.dump(arr[0], fh, ensure_ascii=False, indent=2)
    print("[dump-firsts] wrote to", args.outdir)

if __name__=="__main__":
    main()
