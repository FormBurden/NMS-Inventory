#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, re, sys, glob
from typing import Any, Dict, Iterable, Tuple, Optional



HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

# --- Begin .env fallback (only if needed) ---
def _maybe_load_env_file_for_hg():
    # Only try to read .env if NMS_HG_PATH isn't already present
    if os.getenv("NMS_HG_PATH"):
        return

    # Compute ROOT locally to avoid order issues
    here = os.path.dirname(__file__)
    root = os.path.abspath(os.path.join(here, "..", ".."))
    env_path = os.path.join(root, ".env")

    try:
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    # Strip optional quotes
                    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                        v = v[1:-1]
                    # Don't overwrite already-exported vars
                    if os.getenv(k) is None:
                        os.environ[k] = v
    except Exception:
        # Soft fallback—ignore read/parse errors
        pass

_maybe_load_env_file_for_hg()
# --- End .env fallback ---


# Reuse your decoder + helpers
sys.path.append(HERE)                     # scripts/python
sys.path.append(os.path.join(HERE, "..")) # scripts/
sys.path.append(os.path.join(HERE, "..", "pipeline"))  # scripts/python/pipeline

# --- Early .env priming for NMS_HG_PATH (order-safe) ---
if os.getenv("NMS_HG_PATH") is None:
    _here = os.path.dirname(__file__)
    _root = os.path.abspath(os.path.join(_here, "..", ".."))
    _env = os.path.join(_root, ".env")
    try:
        if os.path.exists(_env):
            with open(_env, "r", encoding="utf-8") as _f:
                for _raw in _f:
                    _line = _raw.strip()
                    if not _line or _line.startswith("#") or "=" not in _line:
                        continue
                    _k, _v = _line.split("=", 1)
                    _k = _k.strip()
                    _v = _v.strip()
                    if (_v.startswith('"') and _v.endswith('"')) or (_v.startswith("'") and _v.endswith("'")):
                        _v = _v[1:-1]
                    if _k == "NMS_HG_PATH" and os.getenv("NMS_HG_PATH") is None:
                        os.environ["NMS_HG_PATH"] = _v
                        break  # we only care about this one key
    except Exception:
        pass
# --- End early .env priming ---


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

def _load_json_from_decoded(json_path: str) -> Any:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)

def _find_latest_decoded_from_manifest(manifest_path: Optional[str] = None) -> Optional[str]:
    """
    Try storage/decoded/_manifest_recent.json → items[0].out_json (or source_path).
    Returns a path to an existing decoded JSON, or None.
    """
    if manifest_path is None:
        manifest_path = os.path.join(ROOT, "storage", "decoded", "_manifest_recent.json")
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            m = json.load(f)
        items = m.get("items") or []
        if items:
            j = items[0]
            cand = j.get("out_json") or j.get("source_path")
            if cand and os.path.isfile(cand):
                return cand
    except Exception:
        pass
    return None


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
    # Allow NMS_HG_PATH to be a directory: pick newest save*.hg
    if p and os.path.isdir(p):
        candidates = sorted(
            glob.glob(os.path.join(p, "save*.hg")),
            key=lambda x: os.path.getmtime(x), reverse=True
        )
        if candidates:
            return candidates[0]

    # Priority 2: .env -> NMS_HG_PATH
    if env_file and os.path.isfile(env_file):
        e = _load_env(env_file)
        p2 = e.get("NMS_HG_PATH")
        # Also allow a directory here: pick newest save*.hg
        if p2 and os.path.isdir(p2):
            candidates = sorted(
                glob.glob(os.path.join(p2, "save*.hg")),
                key=lambda x: os.path.getmtime(x), reverse=True
            )
            if candidates:
                return candidates[0]
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
    ap.add_argument("--decoded", help="Path to decoded JSON (skip HG decode)")
    ap.add_argument("--emit-json", action="store_true", help="Emit JSON (inv_fp/base/mtime/saveid)")
    args = ap.parse_args()

    # Choose input: prefer decoded JSON when provided or discoverable
    data = None
    base = ""
    mtime = ""
    saveid = "default"

    if args.decoded:
        json_path = args.decoded
        if not os.path.isfile(json_path):
            raise SystemExit(f"Decoded JSON not found: {json_path}")
        data = _load_json_from_decoded(json_path)
        base = json_path
        mtime = str(int(os.path.getmtime(json_path)))
        saveid = _derive_saveid(json_path)
    else:
        hg_path = None
        if args.hg:
            hg_path = args.hg
        elif args.latest:
            try:
                hg_path = _find_latest_hg(args.env_file)
            except SystemExit:
                hg_path = None

        if hg_path and os.path.isfile(hg_path):
            data = _load_json_from_hg(hg_path)
            base = hg_path
            mtime = str(int(os.path.getmtime(hg_path)))
            saveid = _derive_saveid(hg_path)
        else:
            # Final fallback: try the most recent decoded manifest
            json_path = _find_latest_decoded_from_manifest()
            if not json_path:
                raise SystemExit("Could not resolve decoded JSON from manifest or locate latest save*.hg.")
            data = _load_json_from_decoded(json_path)
            base = json_path
            mtime = str(int(os.path.getmtime(json_path)))
            saveid = _derive_saveid(json_path)

    rows = compute_rows(data)
    fp = fingerprint_rows(rows)


    # Behavior:
    # - with --latest: default to JSON (so runtime can parse base/mtime/saveid)
    # - with --hg: default to raw hash (backward-compatible), unless --emit-json
    want_json = (getattr(args, "emit_json", False)) or bool(args.latest) or bool(args.decoded)
    if want_json:
        print(json.dumps({"inv_fp": fp, "base": base, "mtime": mtime, "saveid": saveid}, ensure_ascii=False))
    else:
        print(fp)

if __name__ == "__main__":
    sys.exit(main())
