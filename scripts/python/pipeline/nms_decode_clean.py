#!/usr/bin/env python3
import argparse, json, subprocess, sys, tempfile
from pathlib import Path
from typing import Any, Dict, Tuple, List

# ---------- I/O helpers ----------

def _read_bytes(p: Path) -> bytes:
    with p.open("rb") as f:
        return f.read()

def _write_bytes(p: Path, b: bytes) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("wb") as f:
        f.write(b)

# ---------- cleaning / parsing ----------

def _clean_trailing_nuls(data: bytes) -> Tuple[bytes, int]:
    i = len(data)
    while i > 0 and data[i-1] == 0x00:
        i -= 1
    return data[:i], (len(data) - i)

def _extract_top_level_json_bytes(data: bytes) -> bytes:
    """
    Return exactly the first complete top-level JSON object from 'data'.
    Handles UTF-8 bytes directly; if it looks like UTF-16 (BOM or many NULs),
    decode to text first and then crop.
    """
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff") or b"\x00" in data[:128]:
        try:
            text = data.decode("utf-16")
        except Exception as e:
            raise SystemExit(f"[ERR] UTF-16 decode failed: {e}")
        start = text.find("{")
        if start < 0:
            raise SystemExit("[ERR] Could not find '{' in UTF-16 text.")
        depth, in_str, esc = 0, False, False
        end = -1
        for i, ch in enumerate(text[start:], start):
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == "\"":
                    in_str = False
            else:
                if ch == "\"":
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
        if end < 0:
            raise SystemExit("[ERR] Could not find matching '}' for top-level JSON (UTF-16).")
        return text[start:end].encode("utf-8")

    start = data.find(b"{")
    if start < 0:
        prefix = data[:16].hex(" ")
        raise SystemExit(f"[ERR] Could not find '{{' in data. First 16 bytes: {prefix}")
    depth, in_str, esc = 0, False, False
    end = -1
    for i in range(start, len(data)):
        b = data[i]
        if in_str:
            if esc:
                esc = False
            elif b == 0x5C:      # backslash
                esc = True
            elif b == 0x22:      # quote
                in_str = False
        else:
            if b == 0x22:        # quote
                in_str = True
            elif b == 0x7B:      # {
                depth += 1
            elif b == 0x7D:      # }
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
    if end < 0:
        raise SystemExit("[ERR] Could not find matching '}' for top-level JSON (UTF-8).")
    return data[start:end]

def _parse_json_bytes_strict(data: bytes) -> Tuple[Dict[str, Any], int, int]:
    """
    Trim trailing NULs, crop to first complete JSON object, decode, json.loads.
    Returns (json_obj, nul_trimmed_count, junk_trimmed_count).
    Decode order: UTF-8 -> UTF-16 (rare) -> Latin-1 (Windows-1252).
    """
    data, nul_count = _clean_trailing_nuls(data)
    cropped = _extract_top_level_json_bytes(data)

    # Try UTF-8 first
    try:
        return json.loads(cropped.decode("utf-8")), nul_count, (len(data) - len(cropped))
    except UnicodeDecodeError:
        pass

    # Try UTF-16 in case we mis-detected earlier (unlikely here)
    try:
        return json.loads(cropped.decode("utf-16")), nul_count, (len(data) - len(cropped))
    except Exception:
        pass

    # Finally, be permissive: Latin-1 (CP1252-ish) to tolerate 0x80..0x9F bytes
    try:
        return json.loads(cropped.decode("latin-1")), nul_count, (len(data) - len(cropped))
    except Exception as e:
        px = data[:16].hex(" ")
        raise SystemExit(f"[ERR] JSON parse failed after UTF-8/16/Latin-1 attempts: {e}. First 16 bytes: {px}")

# ---------- optional probe ----------

def _probe_season(js: Dict[str, Any]) -> None:
    sd = (js.get("SeasonDescriptor") or {}).get("SeasonId")
    ss = js.get("SeasonState") if isinstance(js.get("SeasonState"), dict) else {}
    ssid = ss.get("SeasonId")
    mi = ss.get("ActiveMilestoneIndex")
    ti = (js.get("SeasonTransferInventoryData") or {}).get("SeasonId")
    print(f"SeasonDescriptor.SeasonId={sd}")
    print(f"SeasonState.SeasonId={ssid}")
    print(f"SeasonState.ActiveMilestoneIndex={mi}")
    print(f"SeasonTransferInventoryData.SeasonId={ti}")

# ---------- nmssavetool runner ----------

def _try_nmssavetool(nmstool: Path, hg_path: Path, tmp_out: Path, subcmds: List[str]) -> Tuple[bytes, bytes, int]:
    """
    Try nmssavetool with several subcommands until one succeeds and writes tmp_out.
    Returns (stdout, stderr, returncode) from the last attempt.
    """
    last = (b"", b"", 0)
    for sc in subcmds:
        cmd = [sys.executable, str(nmstool), sc, str(hg_path), str(tmp_out)]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        last = (proc.stdout, proc.stderr, proc.returncode)
        if proc.returncode == 0 and tmp_out.exists() and tmp_out.stat().st_size > 0:
            return last
    return last

# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description="Decompress NMS .hg to JSON via nmssavetool.py, remove trailing NULs, crop to valid JSON, and handle odd encodings.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--hg", help="Path to a .hg save file (e.g., save3.hg)")
    g.add_argument("--json", help="Path to an already-decoded JSON to clean/validate")
    ap.add_argument("--nmssavetool", help="Path to nmssavetool.py (required with --hg)")
    ap.add_argument("--out", required=True, help="Output JSON file")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print output JSON")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite output if it exists")
    ap.add_argument("--probe-season", action="store_true", help="Print Expedition/Season fields")

    args = ap.parse_args()
    out_path = Path(args.out)
    if out_path.exists() and not args.overwrite:
        raise SystemExit(f"[ERR] Output already exists: {out_path} (use --overwrite)")

    # Acquire raw bytes
    if args.hg:
        if not args.nmssavetool:
            raise SystemExit("[ERR] --nmssavetool is required when using --hg")
        hg_path = Path(args.hg)
        nmstool = Path(args.nmssavetool)
        if not hg_path.exists():
            raise SystemExit(f"[ERR] Missing input: {hg_path}")
        if not nmstool.exists():
            raise SystemExit(f"[ERR] Missing nmssavetool: {nmstool}")

        with tempfile.TemporaryDirectory() as td:
            tmp_out = Path(td) / "decoded.json"
            stdout, stderr, rc = _try_nmssavetool(nmstool, hg_path, tmp_out, ["decompress", "d", "decode"])
            if not tmp_out.exists() or tmp_out.stat().st_size == 0:
                so = (stdout or b"")[:200].decode("utf-8", "replace")
                se = (stderr or b"")[:200].decode("utf-8", "replace")
                msg = se or so or "(no output)"
                raise SystemExit(f"[ERR] nmssavetool did not produce a JSON file (exit {rc}). Output:\n{msg}")
            raw = _read_bytes(tmp_out)
            produced = f"decoded from {hg_path.name}"
    else:
        jpath = Path(args.json)
        if not jpath.exists():
            raise SystemExit(f"[ERR] Missing input: {jpath}")
        raw = _read_bytes(jpath)
        produced = f"loaded from {jpath.name}"

    # Parse strictly
    js, nul_trimmed, junk_trimmed = _parse_json_bytes_strict(raw)

    # Write final JSON
    payload = json.dumps(js, ensure_ascii=False, indent=2).encode("utf-8") if args.pretty \
              else json.dumps(js, separators=(",", ":")).encode("utf-8")
    _write_bytes(out_path, payload)

    print(f"[OK] {produced}")
    print(f"[OK] Cleaned trailing NULs: {nul_trimmed} trimmed")
    if junk_trimmed:
        print(f"[OK] Dropped {junk_trimmed} trailing junk byte(s) after JSON")
    print(f"[OK] Wrote: {out_path} ({out_path.stat().st_size} bytes)")

    if args.probe_season:
        _probe_season(js)

if __name__ == "__main__":
    main()
