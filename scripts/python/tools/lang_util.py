#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lang_util: auto-discovers and loads NMS .lang.json files.

Default search roots (relative to repo root):
- data/lang/*.lang.json
- .cache/aa/pkg/contentFiles/any/any/Assets/json/<locale>/*.lang.json  (AssistantApps)

Locale order:
- env NMS_LANG (comma/semicolon list), else default ["en-us","en","en-gb"]
"""
import os, json, glob
from typing import Dict, List, Iterable, Tuple, Any

AA_BASE     = os.path.join(".cache", "aa", "pkg", "contentFiles", "any", "any", "Assets", "json")
CURATED_DIR = os.path.join("data", "lang")

# --- locale helpers ----------------------------------------------------------
def _norm_locale(s: str) -> str:
    return (s or "").strip().lower()

def parse_locale_list(spec: str) -> List[str]:
    if not spec:
        return []
    out: List[str] = []
    for part in spec.replace(";", ",").split(","):
        loc = _norm_locale(part)
        if loc and loc not in out:
            out.append(loc)
    return out

def default_locale_order() -> List[str]:
    env = os.environ.get("NMS_LANG", "")
    env_list = parse_locale_list(env)
    base = ["en-us", "en", "en-gb"]
    return env_list or base

# --- file discovery ----------------------------------------------------------
def _collect_lang_files_for_locale(loc: str) -> List[str]:
    aa_dir = os.path.join(AA_BASE, loc)
    return sorted(glob.glob(os.path.join(aa_dir, "*.lang.json"))) if os.path.isdir(aa_dir) else []

def _collect_curated_files() -> List[str]:
    return sorted(glob.glob(os.path.join(CURATED_DIR, "*.lang.json"))) if os.path.isdir(CURATED_DIR) else []

def _safe_load_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return json.load(fh)
    except Exception:
        return None

# --- normalization / ingestion ----------------------------------------------
_K_FIELDS = ("Key","key","Id","ID","Name","name")
_V_FIELDS = ("Value","value","Text","text","English","english","String","string")

def _add_pair(dst: Dict[str, str], k: Any, v: Any) -> None:
    if not isinstance(k, str) or not isinstance(v, str):
        return
    key = k[1:] if k.startswith("^") else k
    if key and key.strip():
        dst[key] = v

def _ingest_kv_like(dst: Dict[str, str], obj: Dict[str, Any]) -> bool:
    """
    Try to ingest a single KV item shaped like:
      {"Key":"UI_...", "Value":"Text"} OR {"Id":"UI_...", "Text":"Text"} etc.
    Returns True if consumed as KV.
    """
    k = None; v = None
    for kf in _K_FIELDS:
        if kf in obj and isinstance(obj[kf], str):
            k = obj[kf]; break
    for vf in _V_FIELDS:
        if vf in obj and isinstance(obj[vf], str):
            v = obj[vf]; break
    if k is not None and v is not None:
        _add_pair(dst, k, v)
        return True
    # special case: {"UI_...": "Text"} or {"UI_...": {"Value":"Text"}}
    if len(obj) == 1:
        (only_k, only_v), = obj.items()
        if isinstance(only_k, str):
            if isinstance(only_v, str):
                _add_pair(dst, only_k, only_v)
                return True
            if isinstance(only_v, dict):
                for vf in _V_FIELDS:
                    val = only_v.get(vf)
                    if isinstance(val, str):
                        _add_pair(dst, only_k, val)
                        return True
    return False

def _ingest_any(dst: Dict[str, str], node: Any) -> None:
    """
    Recursively walk arbitrary AA/curated JSON structures and extract
    key->string pairs via the patterns above. Handles:
      - lists of KV objects
      - dicts containing arrays under keys like "Table","Entries","Data","Strings", etc.
      - dict-of-dicts where inner dict holds Value/Text
      - direct dict maps of key->string
    """
    if node is None:
        return
    if isinstance(node, list):
        for it in node:
            if isinstance(it, dict):
                # try KV form first
                if not _ingest_kv_like(dst, it):
                    # fallback: scan the dict recursively
                    _ingest_any(dst, it)
            else:
                _ingest_any(dst, it)
        return
    if isinstance(node, dict):
        # 1) try as a KV-like object
        if _ingest_kv_like(dst, node):
            return
        # 2) try container arrays
        for container in ("Table","Entries","Data","data","items","Strings","strings","values","Values"):
            arr = node.get(container)
            if isinstance(arr, list):
                _ingest_any(dst, arr)
        # 3) dict of key -> (string | dict with Value/Text)
        for k, v in node.items():
            if isinstance(v, str):
                _add_pair(dst, k, v)
            elif isinstance(v, dict):
                if not _ingest_kv_like(dst, {k: v}):
                    _ingest_any(dst, v)
            elif isinstance(v, list):
                _ingest_any(dst, v)
        return
    # primitives ignored

def _normalize_lang_obj(obj: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}
    _ingest_any(out, obj)
    return out

# --- public API --------------------------------------------------------------
def build_lang_map(locale_order: Iterable[str]) -> Tuple[Dict[str, str], Dict[str, int]]:
    """
    Merge maps in this order:
      1) AssistantApps per-locale (first locale in order first)
      2) Curated local data/lang/*.lang.json (overrides / supplements)
    Returns: (lang_map, stats)
    """
    locs = [_norm_locale(x) for x in locale_order if _norm_locale(x)]
    files: List[str] = []
    stats = {"aa_files": 0, "curated_files": 0, "entries": 0}

    for loc in locs:
        aa_files = _collect_lang_files_for_locale(loc)
        files.extend(aa_files)
        stats["aa_files"] += len(aa_files)

    curated = _collect_curated_files()
    files.extend(curated)
    stats["curated_files"] = len(curated)

    merged: Dict[str, str] = {}
    for f in files:
        obj = _safe_load_json(f)
        if obj is None: continue
        mm = _normalize_lang_obj(obj)
        # later files override earlier; curated wins on overlap
        merged.update(mm)

    stats["entries"] = len(merged)
    return merged, stats

def localize(s: str, lang_map: Dict[str, str]) -> str:
    if not isinstance(s, str):
        return s
    if s.startswith("^"):
        return lang_map.get(s[1:], s)
    return s
