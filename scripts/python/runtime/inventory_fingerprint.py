#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inventory_fingerprint.py
Compute a stable fingerprint for the latest decoded save JSON (or a provided one),
along with the raw-save mtime (epoch seconds) and a stable saveid (st_XXXXXXXXXXXXXX).

Outputs compact JSON to stdout:
  {"inv_fp":"<sha256>","base":"<json_path>","mtime":"<epoch>","saveid":"<st_id|default>"}

Usage:
  --latest           Resolve the latest decoded JSON using the manifest/glob fallback
  --decoded <path>   Use the provided decoded JSON path
  --emit-json        (ignored; JSON is always emitted for compatibility)

Exit codes:
  0  success
  1  could not resolve a decoded JSON
  2  decoded JSON unreadable or empty
"""

import sys
import os
import re
import json
import time
import glob
import hashlib
from typing import Optional, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# -------------------------
# Utilities
# -------------------------

def _load_env(env_path: str) -> dict:
    env = {}
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                env[k] = v
    except Exception:
        pass
    return env

def _ensure_env_loaded() -> dict:
    """Always read .env and merge into process env (without overwriting existing entries)."""
    env_path = os.path.join(ROOT, ".env")
    merged = dict(os.environ)
    if os.path.isfile(env_path):
        disk = _load_env(env_path)
        for k, v in disk.items():
            if k not in merged or not merged[k]:
                merged[k] = v
    return merged

def _to_epoch_seconds(val: object) -> Optional[str]:
    """Accepts int/float/str epoch; or 'YYYY-MM-DD HH:MM:SS' in localtime."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return str(int(val))
    s = str(val).strip()
    if not s:
        return None
    if s.isdigit():
        return s
    try:
        tm = time.strptime(s, "%Y-%m-%d %H:%M:%S")
        return str(int(time.mktime(tm)))
    except Exception:
        return None

def _derive_saveid_from_path(path: str) -> Optional[str]:
    m = re.search(r"(st_[0-9]+)", path)
    return m.group(1) if m else None

def _derive_saveid_from_env(env: dict) -> str:
    sid = (env.get("NMS_PROFILE") or "").strip()
    m = re.match(r"(st_[0-9]+)", sid)
    return m.group(1) if m else "default"

# -------------------------
# Resolution helpers
# -------------------------

def _read_manifest() -> Optional[dict]:
    p = os.path.join(ROOT, "storage", "decoded", "_manifest_recent.json")
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _manifest_decoded_path_and_epoch() -> Tuple[Optional[str], Optional[str]]:
    """Return (decoded_json_path, raw_save_epoch_from_manifest) or (None, None)."""
    man = _read_manifest()
    if not man:
        return None, None
    # Try top-level first
    epoch = _to_epoch_seconds(
        man.get("source_mtime") or man.get("src_mtime") or man.get("mtime")
    )
    # Look into items[0]
    items = man.get("items")
    cand = None
    if isinstance(items, list) and items:
        it0 = items[0]
        cand = it0.get("out_json") or it0.get("source_path") or it0.get("decoded_json")
        if not epoch:
            epoch = _to_epoch_seconds(
                it0.get("source_mtime") or it0.get("decoded_mtime") or it0.get("mtime")
            )
    if cand:
        # Normalize candidates with a few fallbacks
        if os.path.isfile(cand):
            return cand, epoch
        alt = os.path.normpath(cand)
        if os.path.isfile(alt):
            return alt, epoch
        # If absolute failed, try relative to project root
        rel = cand
        if cand.startswith("/"):
            try:
                rel = os.path.relpath(cand, ROOT)
            except Exception:
                rel = cand
        guess = os.path.join(ROOT, rel)
        if os.path.isfile(guess):
            return guess, epoch
    return None, epoch

def _find_latest_decoded_glob() -> Optional[str]:
    decoded_dir = os.path.join(ROOT, "storage", "decoded")
    try:
        candidates = glob.glob(os.path.join(decoded_dir, "save*.json"))
        if not candidates:
            return None
        candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return candidates[0]
    except Exception:
        return None

# -------------------------
# Fingerprint computation
# -------------------------

def _sha256_of_json(doc: object) -> str:
    """Stable hash of entire JSON content (sorted keys, no whitespace)."""
    data = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()

def _fingerprint_from_decoded(json_path: str, manifest_epoch: Optional[str], env: dict) -> Optional[dict]:
    if not os.path.isfile(json_path):
        return None
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except Exception:
        return None
    inv_fp = _sha256_of_json(doc)
    # Prefer manifest epoch for raw-save mtime; else fallback to decoded file's mtime
    mtime = manifest_epoch or str(int(os.path.getmtime(json_path)))
    saveid = _derive_saveid_from_path(json_path) or _derive_saveid_from_env(env)
    return {
        "inv_fp": inv_fp,
        "base": json_path,
        "mtime": mtime,
        "saveid": saveid,
    }

# -------------------------
# Main
# -------------------------

def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")

def main() -> int:
    args = sys.argv[1:]
    use_latest = False
    decoded_path = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--latest":
            use_latest = True
        elif a == "--decoded" and i + 1 < len(args):
            decoded_path = args[i + 1]
            i += 1
        elif a == "--emit-json":
            pass  # JSON is always emitted
        else:
            # ignore unknown flags for compatibility
            pass
        i += 1

    env = _ensure_env_loaded()
    if (env.get("INVFP_ENABLED", "1").strip().strip('"') == "0"):
    _emit({})  # empty object => downstream treats as “no candidate fp”
    return 0


    if use_latest and not decoded_path:
        # 1) Manifest first
        cand, epoch = _manifest_decoded_path_and_epoch()
        if not cand:
            # 2) Fallback: newest storage/decoded/save*.json
            cand = _find_latest_decoded_glob()
        if not cand:
            sys.stderr.write("Could not resolve decoded JSON from manifest or locate latest save*.hg.\n")
            return 1
        info = _fingerprint_from_decoded(cand, epoch, env)
        if not info:
            sys.stderr.write("Decoded JSON exists but could not be read/parsed.\n")
            return 2
        _emit(info)
        return 0

    if decoded_path:
        # Allow explicit decoded paths
        man_epoch = _manifest_decoded_path_and_epoch()[1]
        info = _fingerprint_from_decoded(decoded_path, man_epoch, env)
        if not info:
            sys.stderr.write("Decoded JSON exists but could not be read/parsed.\n")
            return 2
        _emit(info)
        return 0

    # If no flags were provided, behave like --latest
    cand, epoch = _manifest_decoded_path_and_epoch()
    if not cand:
        cand = _find_latest_decoded_glob()
    if not cand:
        sys.stderr.write("Could not resolve decoded JSON from manifest or locate latest save*.hg.\n")
        return 1
    info = _fingerprint_from_decoded(cand, epoch, env)
    if not info:
        sys.stderr.write("Decoded JSON exists but could not be read/parsed.\n")
        return 2
    _emit(info)
    return 0


if __name__ == "__main__":
    sys.exit(main())
