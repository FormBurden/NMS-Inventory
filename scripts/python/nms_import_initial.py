#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nms_import_initial.py

Initial import orchestrator with the following features preserved from your long version:
  - Reads WATCH_SAVES_DIRS and NMSSAVETOOL from .env (modules.config.DATA_DIR respected)
  - Age filter window (default 30 days), --since-days / --since-date / --no-age-filter
  - Skips non-save files (mf_*, accountdata) unless --include-mf/--include-account
  - Accepts explicit --initial (JSON/HG) and/or --saves-dirs (one or many)
  - Robust nmssavetool invocation: stdout/stderr/file, “decompress”, -i/-o,
    with BOM/NUL stripping and JSON-slice safety
  - Writes manifest with metadata: generated_at, cutoff, recent_only, decoder_used
  - Decodes into DATA_DIR/.cache/decoded by default; manifest named _manifest_recent.json

Additions/fixes:
  - Delegates to scripts/python/db_import_initial.py to EMIT SQL to STDOUT
  - All human-readable logs go to STDERR (safe to pipe to mariadb)
  - New flag --no-sql to stop after decode/manifest (compat with your old flow)
  - Pass-through --dry-run/--limit to the DB importer

Typical piping:
  python3 scripts/python/nms_import_initial.py --decode \
    --decoder "/path/to/nmssavetool.py" \
    --saves-dirs "/path/with/spaces/st_XXXX" \
  | mariadb -u nms_user -p -D nms_database
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

# ---------- stderr logging ----------
def log(msg: str) -> None:
    sys.stderr.write(msg.rstrip() + "\n")

# ---------- DATA_DIR (project convention) ----------
try:
    from modules.config import DATA_DIR  # type: ignore
except Exception:
    DATA_DIR = str(Path(__file__).resolve().parents[2])

DATA_DIR_PATH = Path(DATA_DIR)
DECODED_DIR = DATA_DIR_PATH / ".cache" / "decoded"
DEFAULT_MANIFEST_NAME = "_manifest_recent.json"
DEFAULT_DAYS = 30
DB_IMPORT = Path(__file__).with_name("db_import_initial.py")

# ---------- dotenv helpers ----------
def load_dotenv(repo_root: Path) -> dict:
    env = {}
    dotenv = repo_root / ".env"
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip().strip("'").strip('"')
    return env

def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]

def split_dirs(value: str) -> List[str]:
    if not value:
        return []
    parts: List[str] = []
    for token in value.replace(";", ",").replace(":", ",").split(","):
        token = token.strip()
        if token:
            parts.append(token)
    return parts

# ---------- time + hashing ----------
def iso_file_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

# ---------- age window ----------
def cutoff_from_args(since_days: int | None, since_date: str | None) -> float:
    if since_date:
        dt = datetime.strptime(since_date, "%Y-%m-%d")
        return dt.timestamp()
    days = since_days if since_days is not None else DEFAULT_DAYS
    return (datetime.now() - timedelta(days=days)).timestamp()

def iter_recent_files(dirs: List[str], cutoff_ts: float, exts=(".hg",)) -> Tuple[List[Path], List[Path]]:
    kept: List[Path] = []
    skipped: List[Path] = []
    for d in dirs:
        base = Path(d).expanduser().resolve()
        if not base.exists():
            log(f"[WARN] ignoring missing directory: {base}")
            continue
        for p in base.rglob("*"):
            if p.is_file() and p.suffix.lower() in exts:
                try:
                    mtime = p.stat().st_mtime
                except FileNotFoundError:
                    continue
                (kept if mtime >= cutoff_ts else skipped).append(p)
    kept.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    skipped.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return kept, skipped

def should_decode(path: Path, include_mf: bool, include_account: bool) -> bool:
    name = path.name.lower()
    if name.startswith("mf_") and not include_mf:
        return False
    if "accountdata" in name and not include_account:
        return False
    return True

# ---------- JSON cleaning ----------
def _clean_json_bytes(raw: bytes) -> bytes:
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    if b"\x00" in raw:
        raw = raw.replace(b"\x00", b"")
    return raw.strip()

def _slice_to_json(raw: bytes) -> bytes:
    raw = _clean_json_bytes(raw)
    if not raw:
        return b""
    i_obj = raw.find(b"{")
    i_arr = raw.find(b"[")
    positions = [x for x in (i_obj, i_arr) if x != -1]
    if not positions:
        return b""
    start = min(positions)
    cand = raw[start:].lstrip()
    return cand if cand[:1] in (b"{", b"[") else b""

# ---------- save-root inference ----------
def infer_save_root(path: Path) -> str:
    for part in path.resolve().parts[::-1]:
        if part.startswith("st_"):
            return part
    return path.parent.name

# ---------- nmssavetool runner ----------
def run_nmssavetool(src: Path, out_json: Path, decoder_hint: str | None) -> None:
    """
    Try stdout-first and file-output patterns, including 'decompress' and -i/-o variants.
    Accept JSON from stdout or stderr; slice to first JSON token; strip BOM/NULs.
    """
    out_json.parent.mkdir(parents=True, exist_ok=True)
    attempts: List[Tuple[List[str], str]] = []
    if decoder_hint:
        tool = str(Path(decoder_hint))
        attempts += [
            # Your decoder (preferred): --in/--out writes directly to file
            (["python3", tool, "--in", str(src), "--out", str(out_json)], "file"),
            # Allow short aliases too (now supported by nms_hg_decoder.py)
            (["python3", tool, "-i", str(src), "-o", str(out_json)], "file"),

            # Fallbacks for nmssavetool-style CLIs (if a user points to that instead)
            (["python3", tool, str(src)], "cap"),
            (["python3", tool, "dump", str(src)], "cap"),
            (["python3", tool, "decode", str(src)], "cap"),
            (["python3", tool, "decompress", str(src), str(out_json)], "file"),
        ]

    else:
        attempts += [
            (["nmssavetool", str(src)], "cap"),
            (["nmssavetool", "dump", str(src)], "cap"),
            (["nmssavetool", "decode", str(src)], "cap"),
            (["nmssavetool", "decompress", str(src), str(out_json)], "file"),
            (["nmssavetool", "-i", str(src), "-o", str(out_json)], "file"),
        ]

    errors: List[str] = []
    for argv, mode in attempts:
        try:
            res = subprocess.run(argv, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if mode == "cap":
                for stream in (res.stdout, res.stderr):
                    data = _slice_to_json(stream or b"")
                    if data:
                        out_json.write_bytes(data)
                        return
                errors.append(f"{' '.join(map(shlex.quote, argv))} -> no JSON on stdout/stderr after slicing")
            else:
                # file mode
                if out_json.exists():
                    data = _slice_to_json(out_json.read_bytes())
                    if data:
                        out_json.write_bytes(data)
                        return
                    out_json.unlink(missing_ok=True)
                    errors.append(f"{' '.join(map(shlex.quote, argv))} -> wrote file but not valid JSON")
                else:
                    # some builds still write JSON to a stream even with -o
                    for stream in (res.stdout, res.stderr):
                        data = _slice_to_json(stream or b"")
                        if data:
                            out_json.write_bytes(data)
                            return
                    errors.append(f"{' '.join(map(shlex.quote, argv))} -> no output file created")
        except subprocess.CalledProcessError as e:
            msg = (e.stderr or b"").decode("utf-8", errors="ignore").strip()
            errors.append(f"{' '.join(map(shlex.quote, argv))}\n{msg}")

    raise SystemExit(
        "[ERR] Failed to decode JSON from save file.\n"
        f"  src: {src}\n"
        f"  out: {out_json}\n"
        f"  decoder: {decoder_hint or 'nmssavetool (PATH)'}\n"
        "  Tried:\n- " + "\n- ".join(errors) + "\n"
        "Hint (manual test):\n"
        f'  python3 "{decoder_hint or "nmssavetool"}" decompress "{src}" "{out_json}"\n'
    )

# ---------- full-parse runner ----------
FULLPARSE_DIR = DATA_DIR_PATH / "output" / "fullparse"

def run_fullparse(in_json: Path, out_full: Path) -> None:
    """
    Invoke our enrichment pass:
      python3 -m scripts.python.nms_fullparse -i <in_json> -o <out_full>
    Runs from repo root so package imports resolve.
    """
    out_full.parent.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, "-m", "scripts.python.nms_fullparse", "-i", str(in_json), "-o", str(out_full)]
    try:
        subprocess.run(argv, check=True, cwd=str(repo_root()))
    except subprocess.CalledProcessError as e:
        msg = getattr(e, "stderr", b"")
        try:
            msg = msg.decode("utf-8", errors="ignore")
        except Exception:
            msg = str(msg)
        log(f"[WARN] full-parse failed for {in_json}: {e}\n{msg}")


# ---------- CLI ----------
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Decode → manifest → (optionally) emit SQL for initial import.")
    # inputs
    ap.add_argument("--initial", help="Path to a single JSON/HG or directory; bypasses WATCH_SAVES_DIRS if set.")
    ap.add_argument("--saves-dirs", nargs="+", help="One or more directories to scan recursively.")
    # decode
    ap.add_argument("--decode", action="store_true", help="Run nmssavetool on selected .hg files.")
    ap.add_argument("--decoder", help="Path to nmssavetool or nmssavetool.py; overrides NMSSAVETOOL in .env.")
    ap.add_argument("--include-mf", action="store_true", help="Also process mf_*.hg files.")
    ap.add_argument("--include-account", action="store_true", help="Also process accountdata.hg files.")
    # windows
    ap.add_argument("--since-days", type=int, help=f"Only include files modified in the last N days (default {DEFAULT_DAYS}).")
    ap.add_argument("--since-date", help="Only include files modified on/after YYYY-MM-DD.")
    ap.add_argument("--no-age-filter", action="store_true", help="Disable the recent-only filter (process everything).")
    # outputs
    ap.add_argument("--out-decoded", default=str(DECODED_DIR), help="Directory for decoded JSON outputs.")
    ap.add_argument("--manifest", help="Full path to manifest JSON (overrides --manifest-name).")
    ap.add_argument("--manifest-name", default=DEFAULT_MANIFEST_NAME, help="Manifest filename within --out-decoded.")
    # DB step
    ap.add_argument("--no-sql", action="store_true", help="Stop after decode/manifest; do not emit SQL.")
    ap.add_argument("--dry-run", action="store_true", help="Parse/report only; DB importer emits no INSERTs.")
    ap.add_argument("--limit", type=int, default=0, help="Process only first N manifest entries.")
    return ap.parse_args()

# ---------- manifest ----------
def write_manifest(items: List[Dict[str, Any]], manifest_path: Path, cutoff_ts: float | None, recent_only: bool, decoder_used: str) -> None:
    doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cutoff": (None if cutoff_ts is None else iso_file_ts(cutoff_ts)),
        "recent_only": recent_only,
        "items": items,
        "decoder_used": decoder_used,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")

# ---------- main ----------
def main() -> None:
    args = parse_args()
    root = repo_root()
    env = load_dotenv(root)

    decoder_hint = args.decoder or env.get("NMSSAVETOOL")
    out_decoded = Path(args.out_decoded).expanduser().resolve()
    out_decoded.mkdir(parents=True, exist_ok=True)

    # Determine input universe (explicit > CLI > .env)
    input_paths: List[str] = []
    if args.initial:
        input_paths = [args.initial]
    elif args.saves_dirs:
        input_paths = args.saves_dirs
    else:
        input_paths = split_dirs(env.get("WATCH_SAVES_DIRS", ""))

    if not input_paths:
        log("[ERR] No input provided. Use --initial / --saves-dirs or WATCH_SAVES_DIRS in .env")
        sys.exit(2)

    # Expand to JSON/HG lists
    json_inputs: List[Path] = []
    hg_dirs: List[str] = []
    for p in input_paths:
        P = Path(p).expanduser().resolve()
        if P.is_file():
            if P.suffix.lower() == ".json":
                json_inputs.append(P)
            elif P.suffix.lower() == ".hg":
                hg_dirs.append(str(P.parent))
            else:
                log(f"[WARN] Unsupported file type (ignored): {P}")
        elif P.is_dir():
            hg_dirs.append(str(P))
        else:
            log(f"[WARN] Ignoring non-existent path: {P}")

    # Age window
    cutoff_ts = None if args.no_age_filter else cutoff_from_args(args.since_days, args.since_date)
    if cutoff_ts is None:
        log("[INFO] Age filter: DISABLED (all files)")
    else:
        log("[INFO] Age filter: Enabled")
        log(f"[INFO] Cutoff: {iso_file_ts(cutoff_ts)}")

    # Collect recent .hg
    kept_hg: List[Path] = []
    skipped_hg: List[Path] = []
    if hg_dirs:
        kept_all, skipped_all = iter_recent_files(hg_dirs, float("-inf") if cutoff_ts is None else cutoff_ts, exts=(".hg",))
        # Drop non-save files unless flags say otherwise
        filtered = [p for p in kept_all if should_decode(p, args.include_mf, args.include_account)]
        dropped  = [p for p in kept_all if p not in filtered]
        kept_hg, skipped_hg = filtered, skipped_all
        if dropped:
            names = ", ".join(sorted({p.name for p in dropped}))
            log(f"[INFO] Skipping non-save files by default: {names}")

        if kept_hg:
            log(f"[OK] {len(kept_hg)} recent .hg files selected:")
            for p in kept_hg:
                log(f"    {p} (root {infer_save_root(p)}; mtime {iso_file_ts(p.stat().st_mtime)})")
        else:
            log("[OK] No recent .hg files found under provided dirs.")

        if skipped_hg:
            log(f"[INFO] {len(skipped_hg)} .hg files skipped as older than cutoff.")

    # JSON inputs (explicit) bypass age filter by design
    if json_inputs:
        log(f"[OK] {len(json_inputs)} explicit JSON file(s) provided (age filter not applied to explicit JSON).")
        for j in json_inputs:
            log(f"    {j}")

    # Early exit if dry-run (planning only)
    if args.dry_run and not args.decode and not json_inputs and not kept_hg:
        log("[DRY-RUN] Nothing to do (no decode targets / JSON).")
        # still continue to importer if manifest exists/synthesizes

    # (A) Decode .hg -> .json (optional)
    items: List[Dict[str, Any]] = []
    decoder_used = decoder_hint or "nmssavetool (PATH)"
    if args.decode and kept_hg:
        for src in kept_hg:
            out_json = out_decoded / (src.stem + ".json")
            log(f"[decode] {src} -> {out_json}")
            run_nmssavetool(src, out_json, decoder_hint)
            try:
                jhash = sha256_file(out_json)
                src_m = iso_file_ts(src.stat().st_mtime)
                dec_m = iso_file_ts(out_json.stat().st_mtime)
            except Exception:
                jhash, src_m, dec_m = "", "", ""
            items.append({
                "source_path": str(src),
                "save_root": infer_save_root(src),
                "source_mtime": src_m,
                "decoded_mtime": dec_m,
                "out_json": str(out_json),
                "json_sha256": jhash,
                "decoder_used": decoder_used
            })

    # Include explicit JSONs into manifest if provided (no decode)
    for j in json_inputs:
        try:
            jhash = sha256_file(j)
            dec_m = iso_file_ts(j.stat().st_mtime)
        except Exception:
            jhash, dec_m = "", ""
        items.append({
            "source_path": str(j),
            "save_root": infer_save_root(j),
            "source_mtime": dec_m,
            "decoded_mtime": dec_m,
            "out_json": str(j),
            "json_sha256": jhash,
            "decoder_used": decoder_used
        })

    # (B) Decide manifest path and write/synthesize
    manifest_path = Path(args.manifest).expanduser().resolve() if args.manifest else (out_decoded / args.manifest_name)
    if items:
        write_manifest(items, manifest_path, (None if cutoff_ts is None else cutoff_ts), cutoff_ts is not None, decoder_used)
        log(f"[OK] Manifest written: {manifest_path}")
    else:
        # No decode/new items; synthesize manifest from existing save*.json in out_decoded
        if not manifest_path.exists():
            cands = sorted(out_decoded.glob("save*.json"))
            synth: List[Dict[str, Any]] = []
            for j in cands:
                try:
                    jhash = sha256_file(j)
                    synth.append({
                        "source_path": str(j),
                        "save_root": infer_save_root(j),
                        "source_mtime": iso_file_ts(j.stat().st_mtime),
                        "decoded_mtime": iso_file_ts(j.stat().st_mtime),
                        "out_json": str(j),
                        "json_sha256": jhash,
                        "decoder_used": decoder_used
                    })
                except Exception:
                    continue
            if synth:
                write_manifest(synth, manifest_path, (None if cutoff_ts is None else cutoff_ts), cutoff_ts is not None, decoder_used)
                log(f"[OK] Manifest synthesized from decoded JSONs: {manifest_path}")
            else:
                log(f"[ERR] Manifest not found and no decoded JSONs in {out_decoded}")
                sys.exit(2)
        else:
            log(f"[OK] Using existing manifest: {manifest_path}")

        # (B2) Full-parse enriched outputs for UI (always; independent of SQL step)
    try:
        targets: List[Path] = []
        if items:
            # Use the just-built manifest items
            for it in items:
                try:
                    targets.append(Path(it["out_json"]))
                except Exception:
                    continue
        else:
            # No new items in this run; load manifest to discover existing decoded JSONs
            try:
                with open(manifest_path, "r", encoding="utf-8", errors="ignore") as fh:
                    mdoc = json.load(fh)
                for it in mdoc.get("items", []):
                    try:
                        targets.append(Path(it["out_json"]))
                    except Exception:
                        continue
            except Exception as e:
                log(f"[WARN] Could not load manifest for full-parse enumeration: {e}")

        # Deduplicate + run
        seen: set[str] = set()
        for j in targets:
            try:
                j_abs = str(j.resolve())
            except Exception:
                j_abs = str(j)
            if j_abs in seen:
                continue
            seen.add(j_abs)

            out_full = FULLPARSE_DIR / (Path(j).stem + ".full.json")
            run_fullparse(Path(j), out_full)
        if seen:
            log(f"[OK] Full-parse completed for {len(seen)} JSON(s) into {FULLPARSE_DIR}")
        else:
            log("[INFO] No JSON targets found for full-parse.")
    except Exception as e:
        log(f"[WARN] Full-parse phase encountered an error: {e}")


    # (C) Delegate to DB importer unless suppressed
    if args.no_sql:
        log("[INFO] --no-sql used: stopping after decode/manifest.")
        return

    cmd = ["python3", "-u", str(DB_IMPORT), "--manifest", str(manifest_path)]
    if args.dry_run:
        cmd.append("--dry-run")
    if args.limit and args.limit > 0:
        cmd.extend(["--limit", str(args.limit)])

    # Inherit our streams so nothing is PIPE-buffered; -u makes Python unbuffered.
    proc = subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr)
    ret = proc.wait()
    if ret != 0:
        sys.exit(ret)



if __name__ == "__main__":
    main()
