#!/usr/bin/env python3
# Parse inventory_fingerprint.py output (JSON or raw) to 4 lines:
# inv_fp\nbase\nmtime\nsaveid
import json, sys, re

def main():
    data = sys.stdin.read().strip()
    # If it looks like JSON, parse expected keys
    try:
        obj = json.loads(data)
        inv_fp = str(obj.get("inv_fp","")).strip()
        base   = str(obj.get("base","")).strip()
        mtime  = str(obj.get("mtime","")).strip()
        saveid = str(obj.get("saveid","default")).strip() or "default"
        if inv_fp:
            print(inv_fp)
            print(base)
            print(mtime)
            print(saveid)
            return 0
    except Exception:
        pass

    # Otherwise, accept a simple 64-hex hash as inv_fp-only
    if re.fullmatch(r"[0-9a-fA-F]{64}", data):
        print(data)
        print("")          # base
        print("")          # mtime
        print("default")   # saveid
        return 0

    # Fallback: emit empty fields to signal "no candidate"
    print("")
    print("")
    print("")
    print("default")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
