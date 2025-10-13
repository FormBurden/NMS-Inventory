#!/usr/bin/env python3
import sys, json, re

def main():
    raw = sys.stdin.read().strip()
    fp = base = mtime = saveid = ""
    if raw:
        try:
            j = json.loads(raw)
            fp = str(j.get("inv_fp",""))
            base = str(j.get("base",""))
            mtime = str(j.get("mtime",""))
            saveid = str(j.get("saveid",""))
        except Exception:
            if "\n" not in raw and "{" not in raw:
                fp = raw.strip()
    if not saveid and base:
        m = re.search(r"(st_[0-9]+)", base)
        if m:
            saveid = m.group(1)
    print(fp)
    print(base)
    print(mtime)
    print(saveid)

if __name__ == "__main__":
    main()
