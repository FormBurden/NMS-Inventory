#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, re, sys, glob
from typing import Any, Dict, Iterable, Tuple, Optional

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

# Reuse your decoder + helpers
sys.path.append(HERE)                     # scripts/python
sys.path.append(os.path.join(HERE, "..")) # scripts/
from nms_hg_decoder import decode_to_json_bytes
from nms_extract_inventory import walk, obj_is_slot, is_progress_token

SANE_CAPS = {50, 100, 101, 200, 250, 500, 801, 1000, 1001, 2000, 9999}

def _amount(slot: dict) -> int:
    a = slot.get("1o9")
    cap = slot.get("F9q")
    if not isinstance(a, int) or not isinstance(cap, int):
        return 0
    if cap in SANE_CAPS and a <= cap:
        return max(a, 0)
    candidates = [x for x in (a, cap) if isinstance(x, int) and x > 0]
    return min(candidates) if candidates else 0

def _infer_owner(path: Iterable[Any]) -> str:
    segs = {str(p) for p in path if isinstance(p, str)}
    if ";l5" in segs: owner = "SUIT"
    elif "P;m" in segs: owner = "SHIP"
    elif "<IP" in segs: owner = "FREIGHTER"
    elif "3Nc" in segs: owner = "STORAGE"
    elif "8ZP" in segs: owner = "VEHICLE"
    else:
        pstr = ".".join(str(p) for p in list(path)[-256:])
        if ".;l5." in pstr: owner = "SUIT"
        elif ".P;m." in pstr: owner = "SHIP"
        elif ".<IP." in pstr: owner = "FREIGHTER"
        elif ".3Nc." in pstr: owner = "STORAGE"
        elif ".8ZP." in pstr: owner = "VEHICLE"
        else: owner = "UNKNOWN"
    if owner == "FREIGHTER":
        owner = "FRIGATE"
    return owner

def _load_json_from_hg(hg_path: str) -> Any:
    with open(hg_path, "rb") as f:
        raw = f.read()
    jb = decode_to_json_bytes(raw, debug=False)
    return json.loads(jb.decode("utf-8"))

def compute_rows(obj: Any):
    totals: Dict[Tuple[str, str], int] = {}
    for path, _parent, _key, val in walk(obj):
        if not isinstance(val, dict): continue
        if not obj_is_slot(val): continue
        rid = val.get("b2n")
        if is_progress_token(rid): continue
        amt = _amount(val)
        if amt <= 0: continue
        owner = _infer_owner(path)
        key = (owner, rid)
        totals[key] = totals.get(key, 0) + amt
    rows = [f"{o}|{rid}|{totals[(o, rid)]}" for (o, rid) in sorted(totals)]
    return rows

def fingerprint_rows(rows) -> str:
    payload = ";".join(rows)
    return hashlib.blake2b(payload.encode("utf-8"), digest_size=32).hexdigest()

# -------- latest save discovery --------
def _load_env(path: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line: continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("'").strip('"')
    except Exception:
        pass
    return out

def _find_latest_hg(env_file: Optional[str]) -> str:
    # Priority 1: env var NMS_HG_PATH
    p = os.environ.get("NMS_HG_PATH")
    if p and os.path.isfile(p):
        return p
    # Priority 2: .env -> NMS_HG_PATH
    if env_file and os.path.isfile(env_file):
        e = _load_env(env_file)
        p2 = e.get("NMS_HG_PATH")
        if p2 and os.path.isfile(p2):
            return p2
        root = e.get("NMS_SAVE_ROOT")
        prof = e.get("NMS_PROFILE")
        if root and prof:
            hg_dir = os.path.join(root, prof)
            candidates = sorted(glob.glob(os.path.join(hg_dir, "save*.hg")),
                               key=lambda x: os.path.getmtime(x), reverse=True)
            if candidates:
                return candidates[0]
    # Priority 3: env vars NMS_SAVE_ROOT + NMS_PROFILE
    root = os.environ.get("NMS_SAVE_ROOT"); prof = os.environ.get("NMS_PROFILE")
    if root and prof:
        hg_dir = os.path.join(root, prof)
        candidates = sorted(glob.glob(os.path.join(hg_dir, "save*.hg")),
                           key=lambda x: os.path.getmtime(x), reverse=True)
        if candidates:
            return candidates[0]
    raise SystemExit("Could not resolve latest save*.hg (set NMS_HG_PATH or NMS_SAVE_ROOT+NMS_PROFILE / .env).")

def _derive_saveid(path: str) -> str:
    m = re.search(r"(st_[0-9]+)", path)
    return m.group(1) if m else "default"

def main():
    ap = argparse.ArgumentParser(description="Inventory-only fingerprint for NMS .hg (with optional metadata).")
    ap.add_argument("--hg", help="Path to save*.hg")
    ap.add_argument("--latest", action="store_true", help="Locate the latest save*.hg using .env / environment.")
    ap.add_argument("--env-file", default=os.path.join(ROOT, ".env"), help="Path to .env (used with --latest).")
    ap.add_argument("--emit-json", action="store_true", help="Emit JSON: {inv_fp, base, mtime, saveid}")
    args = ap.parse_args()

    if not args.hg and not args.latest:
        ap.error("Provide --hg PATH or --latest")

    hg_path = args.hg if args.hg else _find_latest_hg(args.env_file)
    if not os.path.isfile(hg_path):
        raise SystemExit(f"HG path not found: {hg_path}")

    data = _load_json_from_hg(hg_path)
    rows = compute_rows(data)
    fp = fingerprint_rows(rows)
    mtime = str(int(os.path.getmtime(hg_path)))
    saveid = _derive_saveid(hg_path)

    # Behavior:
    # - with --latest: default to JSON (so runtime can parse base/mtime/saveid)
    # - with --hg: default to raw hash (backward-compatible), unless --emit-json
    want_json = args.emit_json or args.latest
    if want_json:
        print(json.dumps({"inv_fp": fp, "base": hg_path, "mtime": mtime, "saveid": saveid}, ensure_ascii=False))
    else:
        print(fp)

if __name__ == "__main__":
    sys.exit(main())
