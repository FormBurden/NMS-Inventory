#!/usr/bin/env python3
import sys, json
def main():
    if len(sys.argv) < 2: return 0
    path = sys.argv[1]
    try:
        with open(path, encoding="utf-8") as f:
            j = json.load(f)
        print(j.get("inv_fp",""))
    except Exception:
        pass
if __name__ == "__main__":
    main()
