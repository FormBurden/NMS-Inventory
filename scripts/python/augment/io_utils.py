# -*- coding: utf-8 -*-
"""I/O and small helpers for the augment pipeline."""
import json, os

def read_json_lenient(path):
    with open(path,'rb') as f:
        buf = f.read()
    # strip trailing NUL/whitespace to be resilient to dump artifacts
    while buf and buf[-1] in (0,10,13,32,9):  # \x00 \n \r space \t
        buf = buf[:-1]
    try:
        return json.loads(buf.decode('utf-8'))
    except UnicodeDecodeError:
        return json.loads(buf.decode('latin-1'))

def safe_get(d, path, default=None):
    cur = d
    for p in path:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return default
    return cur

def load_json(path):
    with open(path,'r',encoding='utf-8') as f:
        return json.load(f)

def save_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp,'w',encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def find_pairs(root='.'):
    full_dir = os.path.join(root, 'output', 'fullparse')
    dec_dir  = os.path.join(root, 'storage', 'decoded')
    pairs = []
    if not os.path.isdir(full_dir) or not os.path.isdir(dec_dir):
        return pairs
    for fn in os.listdir(full_dir):
        if not fn.endswith('.full.json'): 
            continue
        name = fn[:-10]  # strip .full.json
        full_path = os.path.join(full_dir, fn)
        dec_path  = os.path.join(dec_dir, name + '.json')
        if os.path.exists(dec_path):
            pairs.append((full_path, dec_path))
    return pairs
