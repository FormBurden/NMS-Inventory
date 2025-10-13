#!/usr/bin/env python3
import argparse, json
from pathlib import Path
from datetime import datetime, timezone

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--inv-fp", default="")
    ap.add_argument("--base", default="")
    ap.add_argument("--mtime", default="")
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inv_fp": args.inv_fp,
        "base": args.base,
        "mtime": args.mtime,
    }
    with out.open("w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)

if __name__ == "__main__":
    main()
