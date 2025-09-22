#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse, json, os, re, sys
from typing import Any, Dict, List, Optional

# --- tolerant loader for decoded & full JSONs (handles trailing bytes) ---
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

# --- import lang util (same folder) ---
try:
    import lang_util  # scripts/python/tools/lang_util.py
except Exception:
    lang_util = None

# --- simple predicates ---
_HEX_GUID = re.compile(r"^0x[0-9A-Fa-f]{8,}$")
def is_code_like(s: str) -> bool:
    return s.startswith("^") or _HEX_GUID.match(s) is not None

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

# --- name/class/slots helpers ---
def items_key_for_element(elem: Dict[str,Any], sample_info: Dict[str,Any]) -> Optional[str]:
    if not isinstance(elem, dict): return None
    list_keys = [k for k,v in elem.items() if isinstance(v, list) and v and all(isinstance(e,dict) for e in v)]
    if not list_keys: return None
    fk = set(k for k in (sample_info.get("first_keys") or []) if isinstance(k,str) and len(k)<=6)
    ranked = sorted(list_keys, key=lambda k: ((k in fk), len(elem[k])), reverse=True)
    return ranked[0]

def inv_slots_from_element(elem: Dict[str,Any], items_key: Optional[str]) -> int:
    if items_key and isinstance(elem.get(items_key), list):
        return len(elem[items_key])
    best_len = -1
    for k,v in elem.items():
        if isinstance(v,list) and v and all(isinstance(e,dict) for e in v) and len(k)<=6:
            if len(v) > best_len: best_len = len(v)
    return max(best_len, 0)

def map_asset(elem: Dict[str,Any], sample_info: Dict[str,Any], localize) -> Dict[str,Any]:
    # Name: collect shallow + one nested layer, localize ^KEY, pick human-looking
    candidates: List[str] = []
    for k,v in elem.items():
        if isinstance(v,str): candidates.append(localize(v))
        elif isinstance(v,dict):
            for vv in v.values():
                if isinstance(vv,str): candidates.append(localize(vv))
    name=""
    for s in candidates:
        if not s or s.startswith("^"): continue
        score = (1 if " " in s else 0) + (1 if any(c.islower() for c in s) and any(c.isupper() for c in s) else 0)
        if 3 <= len(s) <= 48: score += 1
        if score >= 1 and len(s) > len(name): name = s

    # Class: shallow S/A/B/C
    klass=""
    for v in elem.values():
        if isinstance(v,str) and v in ("S","A","B","C"): klass=v; break
        if isinstance(v,dict):
            for vv in v.values():
                if isinstance(vv,str) and vv in ("S","A","B","C"): klass=vv; break
        if klass: break

    slots = inv_slots_from_element(elem, items_key_for_element(elem, sample_info))
    out={"inv":{"w":0,"h":0,"slots":slots,"tech_count":0}}
    if name:  out["name"]=name
    if klass: out["class"]=klass
    return out

def extract_assets(save: Dict[str,Any], samples: Dict[str,Any], log: List[str], localize) -> Dict[str,Any]:
    res={"ships":[],"multitools":[],"exocraft":[],"freighter":[]}
    for label in ("ships","multitools","exocraft"):
        info = samples.get(label) or {}
        path = info.get("path","")
        arr = get_by_path(save, path)
        if isinstance(arr,list) and arr:
            log.append(f"[assets] {label} via samples path='{path}' len={len(arr)}")
            res[label] = [ map_asset(e, info, localize) for e in arr[:12] if isinstance(e,dict) ]
        else:
            rx={"ships":re.compile(r"\b(PlayerShipBase|Starship)\b",re.I),
                "multitools":re.compile(r"(MULTITOOL\.SCENE|Multi.?Tool)",re.I),
                "exocraft":re.compile(r"\b(Exocraft|Vehicle|Nomad|Roamer|Colossus|Minotaur|Mech)\b",re.I)}[label]
            hits=find_arrays_with_value(save,rx)
            if hits:
                log.append(f"[assets:fallback] {label} via value rx; len={len(hits[0])}")
                res[label] = [ map_asset(e, {}, localize) for e in hits[0][:12] if isinstance(e,dict) ]
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
        res["freighter"]=[ map_asset(fo, {}, localize) ]
    return res

def extract_teleport(save: Dict[str,Any], samples: Dict[str,Any], log: List[str], localize) -> List[Dict[str,Any]]:
    info=samples.get("teleport") or {}
    path=info.get("path","")
    arr=get_by_path(save,path)
    out=[]
    def pick_strings_localized(t: Dict[str,Any]) -> List[str]:
        human=[]; raw=[]
        for v in t.values():
            if isinstance(v,str):
                lv = localize(v)
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

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--decoded",required=True)
    ap.add_argument("--full",required=True)
    ap.add_argument("--samples",help="output/deepdebug/<basename>.assets.samples.json")
    ap.add_argument("--locale", help='Locale priority list, e.g. "en-us,en" (default: env NMS_LANG or "en-us,en,en-gb")')
    ap.add_argument("--in-place",action="store_true")
    args=ap.parse_args()

    # Load samples (explicit or guessed path)
    samples={}
    if args.samples and os.path.exists(args.samples):
        samples=load_json_relaxed(args.samples)
    else:
        base=os.path.splitext(os.path.basename(args.decoded))[0]
        guess=os.path.join("output","deepdebug",f"{base}.assets.samples.json")
        if os.path.exists(guess): samples=load_json_relaxed(guess)

    # Auto-load language map (defaults)
    localize = (lambda s: s)
    lang_stats = {}
    if lang_util:
        loc_order = lang_util.parse_locale_list(args.locale) or lang_util.default_locale_order()
        lang_map, lang_stats = lang_util.build_lang_map(loc_order)
        localize = (lambda s, _m=lang_map: lang_util.localize(s, _m))

    save=load_json_relaxed(args.decoded)
    full=load_json_relaxed(args.full)

    log=[]
    if lang_stats:
        log.append(f"[lang] aa_files={lang_stats.get('aa_files',0)} curated_files={lang_stats.get('curated_files',0)} entries={lang_stats.get('entries',0)}")

    deep={
        "assets":extract_assets(save,samples,log,localize),
        "teleport_history":extract_teleport(save,samples,log,localize),
        "currencies":extract_currencies(save,log),
        "owner_slots":{},
        "extract_log":log[:200],
    }
    rr=full.setdefault("_rollup",{}); rr["deep"]=deep

    if args.in_place:
        save_json(args.full,full); print(f"[deep] updated {args.full}")
    else:
        outp=args.full+".deep.json"; save_json(outp,full); print(f"[deep] wrote {outp}")

if __name__=="__main__":
    main()
