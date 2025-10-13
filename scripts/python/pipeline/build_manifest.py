#!/usr/bin/env python3
import argparse, json
from pathlib import Path
from datetime import datetime, timezone

def main():
    ap = argparse.ArgumentParser(description="Write _manifest_recent.json for the latest decode output.")
    ap.add_argument("--source", required=True, help="Path to source save (save.hg/save2.hg)")
    ap.add_argument("--source-mtime", default="", help="Source mtime (epoch seconds). If empty, stat the source.")
    ap.add_argument("--decoded", required=True, help="Path to decoded JSON that was produced.")
    ap.add_argument("--out", required=True, help="Manifest output path (e.g., storage/decoded/_manifest_recent.json)")
    args = ap.parse_args()

    src = Path(args.source)
    out = Path(args.out)
    decoded = Path(args.decoded)

    # Resolve mtime
    if args.source_mtime:
        try:
            mtime = str(int(float(args.source_mtime)))
        except Exception:
            mtime = ""
    else:
        try:
            mtime = str(int(src.stat().st_mtime))
        except Exception:
            mtime = ""

    doc = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_path": str(src),
        "source_mtime": mtime,
        "out_json": str(decoded),
        "decoder_used": "scripts/python/pipeline/nms_hg_decoder.py",
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
    print(f"[MANIFEST] wrote {out} (source_mtime={mtime or 'unset'})")

if __name__ == "__main__":
    main()
