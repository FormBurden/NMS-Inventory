#!/usr/bin/env python3
import argparse, json, os, subprocess, sys, tempfile
from pathlib import Path
from typing import Any, Dict

def _read_bytes(p: Path) -> bytes:
    with p.open("rb") as f:
        return f.read()

def _write_bytes(p: Path, b: bytes) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("wb") as f:
        f.write(b)

def _clean_trailing_nuls(data: bytes) -> tuple[bytes, int]:
    # Trim any number of trailing \x00 bytes
    i = len(data)
    while i > 0 and data[i-1] == 0:
        i -= 1
    return data[:i], len(data) - i

def _validate_json_bytes(data: bytes) -> Dict[str, Any]:
    # Accept UTF-8 (with/without BOM). Strip BOM if present.
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return json.loads(data.decode("utf-8"))
    except Exception as e:
        raise SystemExit(f"[ERR] JSON parse failed: {e}")

def _summarize_decoder_json(js: Dict[str, Any]) -> str:
    # Lightweight summary for nmssavetool-style decoded JSON
    # Detect containers that have a container type (WA4.rri) and items list (:No)
    def walk(obj):
        if isinstance(obj, dict):
            if "WA4.rri" in obj and ":No" in obj and isinstance(obj[":No"], list):
                yield obj
            for v in obj.values():
                yield from walk(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from walk(v)

    by_kind = {}
    total_items = 0
    containers = 0
    for c in walk(js):
        kind = c.get("WA4.rri", "Unknown")
        items = c.get(":No", [])
        containers += 1
        total_items += len(items)
        by_kind[kind] = by_kind.get(kind, 0) + len(items)

    # Format
    lines = [f"Containers: {containers}, Item stacks: {total_items}"]
    for k in sorted(by_kind.keys()):
        lines.append(f"  - {k}: {by_kind[k]} stacks")
    return "\n".join(lines)

def main():
    ap = argparse.ArgumentParser(description="Decode NMS .hg -> JSON via nmssavetool.py, then clean trailing NULs and validate.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--hg", help="Path to save.hg/save2.hg to decode")
    g.add_argument("--json", help="Path to an already-decoded JSON to clean/validate")
    ap.add_argument("--nmssavetool", default="nmssavetool.py", help="Path to nmssavetool.py (Python, lz4-based).")
    ap.add_argument("--out", required=True, help="Output JSON path (cleaned / pretty if requested).")
    ap.add_argument("--pretty", action="store_true", help="Reformat JSON with indentation.")
    ap.add_argument("--ensure-newline", action="store_true", help="Ensure file ends with a single newline.")
    ap.add_argument("--print-summary", action="store_true", help="Print container/item summary for sanity.")
    ap.add_argument("--overwrite", action="store_true", help="Allow overwriting an existing output file.")
    args = ap.parse_args()

    out_path = Path(args.out)
    if out_path.exists() and not args.overwrite:
        raise SystemExit(f"[ERR] Output exists: {out_path}. Use --overwrite to replace.")

    # Step 1: produce raw JSON bytes (from --json or by running nmssavetool.py)
    if args.json:
        raw = _read_bytes(Path(args.json))
        produced = f"read JSON: {args.json}"
    else:
        nmstool = Path(args.nmssavetool)
        if not nmstool.exists():
            raise SystemExit(f"[ERR] nmssavetool not found at: {nmstool}")
        hg_path = Path(args.hg)
        if not hg_path.exists():
            raise SystemExit(f"[ERR] .hg file not found: {hg_path}")
        with tempfile.TemporaryDirectory() as td:
            tmp_out = Path(td) / "decoded.json"
            # Call: python nmssavetool.py decompress <in.hg> <out.json>
            cmd = [sys.executable, str(nmstool), "decompress", str(hg_path), str(tmp_out)]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0 or not tmp_out.exists():
                sys.stderr.write(proc.stdout + proc.stderr)
                raise SystemExit(f"[ERR] nmssavetool decompress failed (code {proc.returncode}).")
            raw = _read_bytes(tmp_out)
            produced = f"decompressed via nmssavetool.py -> {tmp_out.name}"

    # Step 2: strip trailing NULs
    cleaned, nul_count = _clean_trailing_nuls(raw)

    # Step 3: validate JSON and optionally pretty-print
    js = _validate_json_bytes(cleaned)

    if args.pretty:
        text = json.dumps(js, ensure_ascii=False, indent=2)
        data_out = text.encode("utf-8")
    else:
        data_out = cleaned

    if args.ensure_newline and (len(data_out) == 0 or data_out[-1] != 0x0A):
        data_out += b"\n"

    _write_bytes(out_path, data_out)

    print(f"[OK] {produced}")
    print(f"[OK] Cleaned trailing NULs: {nul_count} trimmed")
    print(f"[OK] Wrote: {out_path} ({out_path.stat().st_size} bytes)")

    if args.print_summary:
        try:
            summary = _summarize_decoder_json(js)
            print(summary)
        except Exception as e:
            print(f"[WARN] Could not summarize containers: {e}")

if __name__ == "__main__":
    main()
