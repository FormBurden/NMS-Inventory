#!/usr/bin/env python3
import sys, json
KEYS = ("source_mtime","src_mtime","sourceMtime","sourceMTime","mtime")
def main():
    if len(sys.argv) < 2: return 0
    p = sys.argv[1]
    try:
        with open(p, encoding="utf-8") as f:
            j = json.load(f)
        for k in KEYS:
            if k in j:
                print(str(j[k]))
                break
    except Exception:
        pass
if __name__ == "__main__":
    main()
