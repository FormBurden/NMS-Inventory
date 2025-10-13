#!/usr/bin/env python3
# Robust .hg → JSON decoder for No Man's Sky with debug mode
# - Scans the entire file for HG block-LZ4 (magic 0xFEEDA1E5) and stitches blocks
# - Also supports gzip, lz4-frame, zlib, or plain JSON
# - Slices exactly the top-level JSON and auto-decodes UTF-8/16/32; falls back to Latin-1
# - --debug prints block stats and writes a raw decompressed stream
import argparse, json, os, sys, gzip, zlib, struct, pathlib

MAGIC_BLOCK = 0xFEEDA1E5
MAGIC_GZIP  = b"\x1f\x8b"
MAGIC_LZ4F  = b"\x04\x22\x4d\x18"  # LZ4 frame

def read_bytes(p: str) -> bytes:
    with open(p, "rb") as f:
        return f.read()

# ---------- JSON helpers ----------

def decode_json_text(text: str) -> bytes:
    obj = json.loads(text)
    # Normalize to UTF-8 JSON
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

def try_decode_variants(b: bytes):
    """
    Try decoding a buffer as JSON text using several encodings.
    Return normalized UTF-8 JSON bytes, or None if all fail.
    """
    # BOM-aware fast paths
    if b.startswith(b"\xEF\xBB\xBF"):
        try: return decode_json_text(b.decode("utf-8"))
        except: pass
    if b.startswith(b"\xFF\xFE\x00\x00"):
        try: return decode_json_text(b.decode("utf-32-le"))
        except: pass
    if b.startswith(b"\x00\x00\xFE\xFF"):
        try: return decode_json_text(b.decode("utf-32-be"))
        except: pass
    if b.startswith(b"\xFF\xFE"):
        try: return decode_json_text(b.decode("utf-16-le"))
        except: pass
    if b.startswith(b"\xFE\xFF"):
        try: return decode_json_text(b.decode("utf-16-be"))
        except: pass

    # No BOM — UTF-8 first
    try:
        return decode_json_text(b.decode("utf-8"))
    except:
        pass

    # Heuristics for UTF-16/32 without BOM
    if len(b) >= 2 and b[:2] in (b'{\x00', b'[\x00'):
        try: return decode_json_text(b.decode("utf-16-le"))
        except: pass
    if len(b) >= 2 and b[:2] in (b'\x00{', b'\x00['):
        try: return decode_json_text(b.decode("utf-16-be"))
        except: pass
    if len(b) >= 4 and b[:4] in (b'{\x00\x00\x00', b'[\x00\x00\x00'):
        try: return decode_json_text(b.decode("utf-32-le"))
        except: pass
    if len(b) >= 4 and b[:4] in (b'\x00\x00\x00{', b'\x00\x00\x00['):
        try: return decode_json_text(b.decode("utf-32-be"))
        except: pass

    # NEW: last resort — Latin-1 (maps raw 0x80–0xFF to U+0080–U+00FF)
    try:
        return decode_json_text(b.decode("latin-1"))
    except:
        return None

def slice_top_level_json(buf: bytes):
    """Return (start,end) of the first complete top-level JSON object/array in a noisy byte buffer."""
    n = len(buf)
    i = 0
    # find first '{' or '[' anywhere
    while i < n and buf[i] not in (ord("{"), ord("[")):
        i += 1
    while i < n:
        if buf[i] not in (ord("{"), ord("[")):
            i += 1; continue
        start = i; depth = 0; in_str = False; esc = False
        j = i
        while j < n:
            ch = buf[j]
            if in_str:
                if esc: esc = False
                elif ch == ord("\\"): esc = True
                elif ch == ord('"'): in_str = False
            else:
                if ch == ord('"'): in_str = True
                elif ch in (ord("{"), ord("[")): depth += 1
                elif ch in (ord("}"), ord("]")):
                    depth -= 1
                    if depth == 0:
                        return (start, j + 1)
            j += 1
        i = start + 1
        while i < n and buf[i] not in (ord("{"), ord("[")):
            i += 1
    return None

def bytes_to_json_bytes(b: bytes, debug=False, dbg_prefix=""):
    """Normalize bytes that *contain* JSON (with possible noise) to canonical UTF-8 JSON bytes."""
    buf = b.rstrip(b"\x00")

    # Fast path: decode entire buffer
    out = try_decode_variants(buf)
    if out is not None:
        if debug: print(f"[DBG] {dbg_prefix}fast-path decoded entire buffer", file=sys.stderr)
        return out

    # Slice exact JSON and try again
    sl = slice_top_level_json(buf)
    if sl is not None:
        start, end = sl
        if debug:
            print(f"[DBG] {dbg_prefix}sliced JSON segment: start={start} end={end} len={end-start}", file=sys.stderr)
        core = buf[start:end]
        out = try_decode_variants(core)
        if out is not None:
            return out

    # Heuristic fallback: cut at the last closing brace/bracket and try
    last_brace = max(buf.rfind(b"}"), buf.rfind(b"]"))
    if last_brace != -1:
        core = buf[: last_brace + 1]
        if debug:
            print(f"[DBG] {dbg_prefix}fallback slice to last brace: end={last_brace+1}", file=sys.stderr)
        out = try_decode_variants(core)
        if out is not None:
            return out

    raise RuntimeError("Could not locate/decode top-level JSON (encoding or slicing failed).")

# ---------- container decoders ----------

def decode_hg_blocks_scan_all(b: bytes, debug=False):
    """
    Scan the entire file for HG blocks and stitch all valid ones:
      [magic=0xFEEDA1E5][comp_sz][decomp_sz][pad=0][comp_bytes]
    """
    try:
        import lz4.block as lz4b  # pip install lz4
    except Exception:
        raise RuntimeError("python-lz4 is required (pip install lz4) to decode HG block saves.")
    out = bytearray()
    magic_bytes = struct.pack("<I", MAGIC_BLOCK)
    pos = 0
    n = len(b)
    found = []
    while True:
        idx = b.find(magic_bytes, pos)
        if idx < 0 or idx + 16 > n:
            break
        try:
            magic, comp_sz, decomp_sz, _pad = struct.unpack_from("<IIII", b, idx)
            if magic != MAGIC_BLOCK or comp_sz == 0:
                pos = idx + 4
                continue
            start = idx + 16
            end = start + comp_sz
            if end > n:
                pos = idx + 4
                continue
            chunk = b[start:end]
            try:
                dec = lz4b.decompress(chunk, uncompressed_size=decomp_sz)
            except Exception:
                # false positive magic inside random data; skip ahead a byte
                pos = idx + 1
                continue
            out += dec
            found.append((idx, comp_sz, decomp_sz))
            pos = end
        except Exception:
            pos = idx + 1
    if debug:
        print(f"[DBG] HG blocks found: {len(found)}", file=sys.stderr)
        for i,(off,cs,ds) in enumerate(found[:20]):
            print(f"[DBG]   blk{i:02d} @ {off}  comp={cs}  decomp={ds}", file=sys.stderr)
        if len(found) > 20:
            print("[DBG]   ...", file=sys.stderr)
    if not found:
        raise RuntimeError("HG block magic not found anywhere in file.")
    return bytes(out), found

def decode_gzip(b: bytes):
    try:
        return gzip.decompress(b)
    except Exception:
        return None

def decode_lz4_frame(b: bytes):
    if not b.startswith(MAGIC_LZ4F):
        return None
    try:
        import lz4.frame as lz4f  # pip install lz4
    except Exception:
        raise RuntimeError("python-lz4 is required (pip install lz4) for LZ4 frame decoding.")
    try:
        return lz4f.decompress(b)
    except Exception:
        return None

def decode_zlib(b: bytes):
    try:
        return zlib.decompress(b)
    except Exception:
        return None

# ---------- orchestrator ----------

def decode_to_json_bytes(raw: bytes, debug=False, outdir: pathlib.Path | None = None) -> bytes:
    # 0) Plain JSON?
    out = try_decode_variants(raw)
    if out is not None:
        if debug: print("[DBG] plain JSON detected", file=sys.stderr)
        return out

    # 1) HG blocks (scan whole file)
    try:
        dec, found = decode_hg_blocks_scan_all(raw, debug=debug)
        if debug:
            print(f"[DBG] total decompressed bytes = {len(dec)}", file=sys.stderr)
        if outdir:
            outdir.mkdir(parents=True, exist_ok=True)
            (outdir / "raw_decompressed.bin").write_bytes(dec)
        return bytes_to_json_bytes(dec, debug=debug, dbg_prefix="HG: ")
    except Exception as e:
        if debug: print(f"[DBG] HG blocks path failed: {e}", file=sys.stderr)

    # 2) gzip
    gz = decode_gzip(raw)
    if gz is not None:
        if debug: print("[DBG] gzip detected", file=sys.stderr)
        return bytes_to_json_bytes(gz, debug=debug, dbg_prefix="GZ: ")

    # 3) lz4-frame
    lzf = decode_lz4_frame(raw)
    if lzf is not None:
        if debug: print("[DBG] lz4-frame detected", file=sys.stderr)
        return bytes_to_json_bytes(lzf, debug=debug, dbg_prefix="LZ4F: ")

    # 4) zlib
    zl = decode_zlib(raw)
    if zl is not None:
        if debug: print("[DBG] zlib detected", file=sys.stderr)
        return bytes_to_json_bytes(zl, debug=debug, dbg_prefix="ZL: ")

    # 5) last-chance: strip NULs and try plain encodings
    out = try_decode_variants(raw.rstrip(b"\x00"))
    if out is not None:
        if debug: print("[DBG] last-chance plain decode worked", file=sys.stderr)
        return out

    raise RuntimeError("Could not decode: not JSON, HG block-LZ4, gzip, lz4-frame, or zlib (or JSON invalid).")

def main():
    ap = argparse.ArgumentParser(description="Decode No Man's Sky .hg save → clean JSON")
    ap.add_argument("-i", "--in", dest="inp", required=True, help="Input .hg or .json")
    ap.add_argument("-o", "--out", dest="out", required=True, help="Output JSON path")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    ap.add_argument("--debug", action="store_true", help="Verbose diagnostics and raw dump")
    args = ap.parse_args()

    raw = read_bytes(args.inp)
    outdir = pathlib.Path(args.out).parent / ".dbg" if args.debug else None
    json_bytes = decode_to_json_bytes(raw, debug=args.debug, outdir=outdir)

    if args.pretty:
        obj = json.loads(json_bytes.decode("utf-8"))
        json_bytes = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "wb") as f:
        f.write(json_bytes)

    print(f"[OK] Decoded -> {args.out} ({len(json_bytes)} bytes)")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERR] {e}", file=sys.stderr)
        sys.exit(2)
