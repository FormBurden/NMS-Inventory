#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse, json, os, re, sys
from typing import Any, Dict, List, Optional

# ---------- tolerant loader ----------
def load_json_relaxed(path: str) -> Any:
    import json as _j
    s = open(path, "r", encoding="utf-8", errors="ignore").read()
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
            if depth==0: return _j.loads(s[start:j+1])
    for line in s.splitlines():
        t=line.strip()
        if t and t[0] in "[{]":
            try: return _j.loads(t)
            except: pass
    raise

def save_json(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        json.dump(data, fh, ensure_ascii=False)

def as_int(x: Any, d: int = 0) -> int:
    try: return int(x)
    except: return d

# ---------- simple predicates ----------
_HEX_GUID = re.compile(r"^0x[0-9A-Fa-f]{8,}$")
def is_code_like(s: str) -> bool:
    return s.startswith("^") or _HEX_GUID.match(s) is not None

# --- optional localization (for strings like ^UI_...) ---
LANG: Dict[str, str] = {}

def load_lang_map(path: str) -> None:
    """Load a simple key->string map for localizing ^KEY tokens."""
    global LANG
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            m = json.load(fh)
        # Normalize: accept keys with or without leading ^
        LANG = { (k[1:] if isinstance(k, str) and k.startswith("^") else k): v
                 for k, v in m.items() if isinstance(k, str) and isinstance(v, str) }
    except Exception:
        LANG = {}

def nms_localize(s: str) -> str:
    """If s looks like ^KEY and exists in LANG, return localized; else return s unchanged."""
    if isinstance(s, str) and s.startswith("^"):
        key = s[1:]
        return LANG.get(key, s)
    return s


def any_str_matches(x: Any, rx: re.Pattern, limit: int = 1) -> bool:
    found=0
    def walk(n):
        nonlocal found
        if found>=limit: return
        if isinstance(n,dict):
            for v in n.values(): walk(v)
        elif isinstance(n,list):
            for v in n[:8]: walk(v)
        elif isinstance(n,str):
            if rx.search(n): found+=1
    walk(x); return found>0

def find_arrays_with_value(save: Any, rx: re.Pattern, max_hits: int = 8) -> List[List[Any]]:
    hits=[]
    def walk(n):
        nonlocal hits
        if len(hits)>=max_hits: return
        if isinstance(n,dict):
            for v in n.values(): walk(v)
        elif isinstance(n,list):
            if any_str_matches(n,rx,1): hits.append(n)
            for v in n[:6]: walk(v)
    walk(save); return hits

def get_by_path(root: Any, path: str) -> Optional[Any]:
    if not path: return root
    cur=root
    for seg in path.split("."):
        if seg=="": continue
        if not isinstance(cur,dict): return None
        if seg not in cur: return None
        cur=cur[seg]
    return cur

# ---------- name/class/slots helpers ----------
def pick_name(d: Dict[str, Any]) -> str:
    best=""
    for k,v in d.items():
        if isinstance(v,str) and not is_code_like(v):
            # prefer names with spaces / mixed case and reasonable length
            score = (1 if " " in v else 0) + (1 if any(c.islower() for c in v) and any(c.isupper() for c in v) else 0)
            if 3 <= len(v) <= 48: score += 1
            if score >= 1 and len(v) > len(best): best=v
    return best

def pick_class(d: Dict[str, Any]) -> str:
    # exact S/A/B/C somewhere shallow
    for v in d.values():
        if isinstance(v,str) and v in ("S","A","B","C"): return v
        if isinstance(v,dict):
            for vv in v.values():
                if isinstance(vv,str) and vv in ("S","A","B","C"): return vv
    return ""

def detect_items_key_from_samples(sample_info: Dict[str,Any]) -> Optional[str]:
    # Look into first_keys and flat_keys for a likely items array key (e.g., "kr6")
    fk = sample_info.get("first_keys") or []
    fl = sample_info.get("flat_keys")  or []
    # prefer short keys that also appear as "[0]" in flat_keys (means list)
    candidates = []
    for k in fk:
        if not isinstance(k,str): continue
        if len(k) > 6: continue
        if any(s.startswith(f"{k}[0]") or s == k for s in fl):
            candidates.append(k)
    # fallback: any short key
    if not candidates:
        candidates = [k for k in fk if isinstance(k,str) and len(k) <= 6]
    return candidates[0] if candidates else None

def items_key_for_element(elem: Dict[str,Any], sample_info: Dict[str,Any]) -> Optional[str]:
    """
    Choose the real items array key for THIS element:
      1) keys that are lists-of-dicts in elem
      2) prefer keys also present in samples.first_keys (short names)
      3) break ties by longer list length
    """
    if not isinstance(elem, dict): return None
    list_keys = [k for k,v in elem.items() if isinstance(v, list) and v and all(isinstance(e,dict) for e in v)]
    if not list_keys: return None
    fk = set(k for k in (sample_info.get("first_keys") or []) if isinstance(k,str) and len(k)<=6)
    ranked = sorted(list_keys, key=lambda k: ((k in fk), len(elem[k])), reverse=True)
    return ranked[0]

def inv_slots_from_element(elem: Dict[str,Any], items_key: Optional[str]) -> int:
    if items_key and isinstance(elem.get(items_key), list):
        return len(elem[items_key])
    # fallback: biggest short-named list of dicts
    best_len = -1
    for k,v in elem.items():
        if isinstance(v,list) and v and all(isinstance(e,dict) for e in v) and len(k)<=6:
            if len(v) > best_len: best_len = len(v)
    return max(best_len, 0)

def map_asset(elem: Dict[str,Any], sample_info: Dict[str,Any]) -> Dict[str,Any]:
    # Name: scan shallow + one nested layer for candidate strings, localize ^KEYs, and choose a human-looking one.
    candidates: List[str] = []
    for k,v in elem.items():
        if isinstance(v,str):
            candidates.append(nms_localize(v))
        elif isinstance(v,dict):
            for vv in v.values():
                if isinstance(vv,str):
                    candidates.append(nms_localize(vv))
    name = ""
    for s in candidates:
        if not s or s.startswith("^"):  # unresolved ^KEY
            continue
        # basic heuristics: contains space or mixed case or decent length
        score = (1 if " " in s else 0) + (1 if any(c.islower() for c in s) and any(c.isupper() for c in s) else 0)
        if 3 <= len(s) <= 48: score += 1
        if score >= 1 and len(s) > len(name):
            name = s

    # Class: shallow S/A/B/C if present
    klass=""
    for v in elem.values():
        if isinstance(v,str) and v in ("S","A","B","C"): klass=v; break
        if isinstance(v,dict):
            for vv in v.values():
                if isinstance(vv,str) and vv in ("S","A","B","C"): klass=vv; break
        if klass: break

    # Slots from the real items list (per-element key)
    items_key = items_key_for_element(elem, sample_info)
    slots = inv_slots_from_element(elem, items_key)

    out={"inv":{"w":0,"h":0,"slots":slots,"tech_count":0}}
    if name:  out["name"]=name
    if klass: out["class"]=klass
    return out



# ---------- extractors ----------
def extract_assets(save: Dict[str,Any], samples: Dict[str,Any], log: List[str]) -> Dict[str,Any]:
    res={"ships":[],"multitools":[],"exocraft":[],"freighter":[]}
    for label in ("ships","multitools","exocraft"):
        info = samples.get(label) or {}
        path = info.get("path","")
        items_key = detect_items_key_from_samples(info)
        arr = get_by_path(save, path)
        if isinstance(arr,list) and arr:
            log.append(f"[assets] {label} via samples path='{path}' len={len(arr)}")
            res[label] = [ map_asset(e, info) for e in arr[:12] if isinstance(e,dict) ]
        else:
            rx={"ships":re.compile(r"\b(PlayerShipBase|Starship)\b",re.I),
                "multitools":re.compile(r"(MULTITOOL\.SCENE|Multi.?Tool)",re.I),
                "exocraft":re.compile(r"\b(Exocraft|Vehicle|Nomad|Roamer|Colossus|Minotaur|Mech)\b",re.I)}[label]
            hits=find_arrays_with_value(save,rx)
            if hits:
                log.append(f"[assets:fallback] {label} via value rx; len={len(hits[0])}")
                res[label] = [ map_asset(e, {}) for e in hits[0][:12] if isinstance(e,dict) ]
    # freighter: value match
    fr_rx=re.compile(r"\b(Freighter|FreighterBase|FreighterCargo|Capital Ship)\b",re.I)
    def find_object(n):
        if isinstance(n,dict):
            if any_str_matches(n, fr_rx, 1): return n
            for v in n.values():
                r=find_object(v)
                if r is not None: return r
        elif isinstance(n,list):
            for v in n[:8]:
                r=find_object(v)
                if r is not None: return r
        return None
    fo=find_object(save)
    if isinstance(fo,dict):
        log.append("[assets] freighter via value rx")
        res["freighter"]=[ map_asset(fo, None) ]
    return res

def extract_teleport(save: Dict[str,Any], samples: Dict[str,Any], log: List[str]) -> List[Dict[str,Any]]:
    info=samples.get("teleport") or {}
    path=info.get("path","")
    arr=get_by_path(save,path)
    out=[]
    def pick_strings_localized(t: Dict[str,Any]) -> List[str]:
        # Prefer localized/human strings; skip raw ^KEY unless we can't find anything else.
        human=[]; raw=[]
        for v in t.values():
            if isinstance(v,str):
                lv = nms_localize(v)
                raw.append(lv)
                if not lv.startswith("^") and not is_code_like(lv):
                    human.append(lv)
                if len(human)>=3: break
        return human if human else raw[:3]
    if isinstance(arr,list) and arr:
        log.append(f"[teleport] via samples path='{path}' len={len(arr)}")
        for t in arr[:16]:
            if not isinstance(t,dict): continue
            vals=pick_strings_localized(t)
            rec={}
            if len(vals)>0 and vals[0]: rec["label"]=vals[0]
            if len(vals)>1 and vals[1]: rec["system"]=vals[1]
            if len(vals)>2 and vals[2]: rec["planet"]=vals[2]
            if rec: out.append(rec)
    else:
        rx=re.compile(r"\b(teleport|teleporter|portal|recent destinations?)\b",re.I)
        hits=find_arrays_with_value(save,rx)
        if hits:
            log.append(f"[teleport:fallback] value rx; len={len(hits[0])}")
            for t in hits[0][:16]:
                if isinstance(t,dict):
                    vals=pick_strings_localized(t)
                    if vals and vals[0]: out.append({"label": vals[0]})
    return out



def extract_currencies(save: Dict[str, Any], log: List[str]) -> Dict[str,int]:
    out={}
    def walk(n,path:str):
        if isinstance(n,dict):
            if 1<=len(n)<=10 and all(isinstance(v,(int,float)) for v in n.values()):
                low=path.lower(); val=sum(as_int(v,0) for v in n.values())
                if "unit" in low: out["units"]=max(out.get("units",0),val)
                if "nan" in low: out["nanites"]=max(out.get("nanites",0),val)
                if "quick" in low or ".qs" in low: out["quicksilver"]=max(out.get("quicksilver",0),val)
            for k,v in n.items(): walk(v, f"{path}.{k}" if path else k)
        elif isinstance(n,list):
            for i,v in enumerate(n[:8]): walk(v, f"{path}[{i}]")
    walk(save,""); return out

# ---------- main ----------
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--decoded",required=True)
    ap.add_argument("--full",required=True)
    ap.add_argument("--samples",help="output/deepdebug/<basename>.assets.samples.json")
    ap.add_argument("--in-place",action="store_true")
    ap.add_argument("--lang", help="Path to a JSON key->string map to translate ^KEY tokens")
    args=ap.parse_args()

    # optional localization map
    if args.lang and os.path.exists(args.lang):
        load_lang_map(args.lang)


    # load samples (explicit or guessed path)
    samples={}
    if args.samples and os.path.exists(args.samples):
        samples=load_json_relaxed(args.samples)
    else:
        base=os.path.splitext(os.path.basename(args.decoded))[0]
        guess=os.path.join("output","deepdebug",f"{base}.assets.samples.json")
        if os.path.exists(guess): samples=load_json_relaxed(guess)

    save=load_json_relaxed(args.decoded)
    full=load_json_relaxed(args.full)

    log=[]
    deep={
        "assets":extract_assets(save,samples,log),
        "teleport_history":extract_teleport(save,samples,log),
        "currencies":extract_currencies(save,log),
        "owner_slots":{},  # can be filled later with precise owners
        "extract_log":log[:200],
    }
    rr=full.setdefault("_rollup",{}); rr["deep"]=deep

    if args.in_place:
        save_json(args.full,full); print(f"[deep] updated {args.full}")
    else:
        outp=args.full+".deep.json"; save_json(outp,full); print(f"[deep] wrote {outp}")

if __name__=="__main__":
    main()
