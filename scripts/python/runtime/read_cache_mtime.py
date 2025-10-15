#!/usr/bin/env python3
import sys, json
def main():
    if len(sys.argv) < 2:
        return 0
    p = sys.argv[1]
    try:
        with open(p, "r", encoding="utf-8") as f:
            j = json.load(f)
        m = j.get("mtime", "")
        if isinstance(m, (int, float)):
            print(int(m))
        elif isinstance(m, str):
            print(m)
    except Exception:
        pass
if __name__ == "__main__":
    main()
