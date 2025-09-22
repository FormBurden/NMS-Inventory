#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scan decoded save JSONs to locate container slot arrays and emit a concise map.
- Looks for dict keys ending with 'hl?' that contain a list of slot coords
  (items typically have keys like '>Qh', 'XJ>' for x/y).
- Writes both JSON and TXT summaries under .cache/probes/.
Usage:
  python3 scripts/python/tools/probe_decoded_inventory_shapes.py storage/decoded/savenormal.json storage/decoded/saveexpedition.json
"""
import json, os, sys
from typing import Any, Dict, List, Tuple

def load_lenient(path:str):
    with open(path,'rb') as f:
        buf=f.read()
    while buf and buf[-1] in b'\x00\r\n \t': buf=buf[:-1]
    try:
        return json.loads(buf.decode('utf-8'))
    except UnicodeDecodeError:
        return json.loads(buf.decode('latin-1'))

def walk(obj: Any, path: List[str], hits: List[Dict[str,Any]]):
    if isinstance(obj, dict):
        for k,v in obj.items():
            p2 = path+[k]
            # slot arrays often live under keys named ... 'hl?'
            if isinstance(v, list) and isinstance(k, str) and k.endswith('hl?'):
                entry = {
                    'path': '/'.join(p2),
                    'count': len(v),
                    'keys_in_elements': sorted(list({kk for it in v if isinstance(it, dict) for kk in it.keys()}))[:6],
                }
                hits.append(entry)
            # keep walking
            walk(v, p2, hits)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:50]):  # cap to keep it quick
            walk(v, path+[f'[{i}]'], hits)

def summarize(decoded_path: str):
    root = load_lenient(decoded_path)
    v = root
    hits: List[Dict[str,Any]] = []
    walk(v, [], hits)
    # group by the parent 2–3 keys so we can see likely owners/sections
    for h in hits:
        parts = h['path'].split('/')
        parent = '/'.join(parts[:-1])
        h['parent'] = parent
        h['tail'] = parts[-1]
    # light sort: by count desc then path
    hits.sort(key=lambda x: (-x['count'], x['path']))
    return hits

def save_outputs(decoded_path: str, hits: List[Dict[str,Any]]):
    os.makedirs('.cache/probes', exist_ok=True)
    base = os.path.splitext(os.path.basename(decoded_path))[0]
    jpath = f'.cache/probes/{base}.slots.json'
    tpath = f'.cache/probes/{base}.slots.txt'
    with open(jpath,'w',encoding='utf-8') as f:
        json.dump(hits, f, ensure_ascii=False, indent=2)
    with open(tpath,'w',encoding='utf-8') as f:
        for h in hits:
            f.write(f"{h['count']:>4}  {h['parent']}  :: {h['tail']}  keys={','.join(h['keys_in_elements'])}\n")
    return jpath, tpath

def main():
    if len(sys.argv) < 2:
        print("Usage: probe_decoded_inventory_shapes.py storage/decoded/<file>.json [...]", file=sys.stderr)
        sys.exit(2)
    for p in sys.argv[1:]:
        j = summarize(p)
        jpath, tpath = save_outputs(p, j)
        print(f"[probe] {p} → {jpath} ; {tpath}")

if __name__ == '__main__':
    main()
