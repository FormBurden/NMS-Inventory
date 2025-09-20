#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nms_import_initial.py
- Initial import helper that ONLY targets "recent" save files by default.
- Decodes .hg -> JSON via nmssavetool.
- Emits a JSON manifest alongside decoded outputs for DB import steps.

Defaults:
  - Recent window: 30 days (override with --since-days or --since-date)
  - Reads WATCH_SAVES_DIRS and NMSSAVETOOL from .env
  - Outputs decoded JSON into DATA_DIR/.cache/decoded
  - Writes manifest: _manifest_recent.json in the decoded dir

Usage examples:
  Dry run:
    python3 scripts/python/nms_import_initial.py --dry-run

  Decode recent files:
    python3 scripts/python/nms_import_initial.py --decode

  Extend window to 90 days:
    python3 scripts/python/nms_import_initial.py --decode --since-days 90

  Disable age filter:
    python3 scripts/python/nms_import_initial.py --decode --no-age-filter
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple

# Project convention (per your standing instruction #28)
try:
    from modules.config import DATA_DIR  # type: ignore
except Exception:
    # scripts/python/ -> repo root is parents[2]
    DATA_DIR = str(Path(__file__).resolve().parents[2])

DEFAULT_DAYS = 30


# ---------------------------
# Utilities
# ---------------------------

def resolve_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


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


def split_dirs(value: str) -> List[str]:
    if not value:
        return []
    parts: List[str] = []
    for token in value.replace(";", ",").replace(":", ",").split(","):
        token = token.strip()
        if token:
            parts.append(token)
    return parts


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
            print(f"[warn] ignoring missing directory: {base}")
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


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def default_decoded_dir() -> Path:
    return Path(DATA_DIR) / ".cache" / "decoded"


# --- replace this whole function in scripts/python/nms_import_initial.py ---
def _clean_json_bytes(raw: bytes) -> bytes:
    """Strip UTF-8 BOM and any NULs; trim whitespace."""
    # UTF-8 BOM
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    # Drop embedded/terminal NULs (nmssavetool sometimes leaves a trailing NUL)
    if b"\x00" in raw:
        raw = raw.replace(b"\x00", b"")
    return raw.strip()

def _looks_like_json(raw: bytes) -> bool:
    s = raw.lstrip()
    return len(s) > 0 and s[:1] in (b"{", b"[")

def run_nmssavetool(src: Path, out_json: Path, decoder_hint: str | None) -> None:
    """
    Decode 'src' .hg into 'out_json' JSON using nmssavetool. We consider it a failure if:
      - the tool exits nonzero, OR
      - it produces empty output, OR
      - the bytes don't look like JSON after cleaning BOM/NUL.
    """
    out_json.parent.mkdir(parents=True, exist_ok=True)
    candidates: list[str] = []

    if decoder_hint:
        hint_path = Path(decoder_hint)
        if hint_path.exists():
            candidates.append(f"python3 {shlex.quote(str(hint_path))} {shlex.quote(str(src))}")
        else:
            candidates.append(f"{shlex.quote(decoder_hint)} {shlex.quote(str(src))}")

    # Try bare nmssavetool on PATH last
    candidates.append(f"nmssavetool {shlex.quote(str(src))}")

    last_err = ""
    for base_cmd in candidates:
        # Mode 1: capture stdout
        try:
            res = subprocess.run(base_cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            raw = _clean_json_bytes(res.stdout or b"")
            if raw and _looks_like_json(raw):
                out_json.write_bytes(raw)
                return
        except subprocess.CalledProcessError as e:
            last_err = f"{e}\n{getattr(e, 'stderr', b'').decode(errors='ignore')}"

        # Mode 2: ask tool to write to file via -o
        try:
            res2 = subprocess.run(f"{base_cmd} -o {shlex.quote(str(out_json))}",
                                  shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if out_json.exists():
                raw = _clean_json_bytes(out_json.read_bytes())
                if raw and _looks_like_json(raw):
                    out_json.write_bytes(raw)  # rewrite cleaned
                    return
        except subprocess.CalledProcessError as e2:
            last_err = f"{last_err}\n{oct(e2.returncode)}\n{getattr(e2, 'stderr', b'').decode(errors='ignore')}"

    raise SystemExit(f"[ERR] Failed to decode {src} (no valid JSON). "
                     f"Hint: set NMSSAVETOOL in .env to the exact nmssavetool.py. Logs: {last_err}")
# --- end replacement ---


def infer_save_root(path: Path) -> str:
    """
    Returns the first directory component that starts with 'st_' (searching upward).
    If none is found, falls back to the immediate parent directory name.
    """
    parts = list(path.resolve().parts)
    # search from leaf upward
    for part in reversed(parts):
        if part.startswith("st_"):
            return part
    return path.parent.name


def fmt_age(ts: float) -> str:
    dt = datetime.fromtimestamp(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def sha256_file(p: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------
# Main
# ---------------------------

def main() -> None:
    repo_root = resolve_repo_root()
    env = load_dotenv(repo_root)

    parser = argparse.ArgumentParser(description="Initial NMS import that respects recent-only file selection.")
    parser.add_argument("--initial", help="Path to a single JSON/HG or to a directory. If omitted, uses WATCH_SAVES_DIRS.")
    parser.add_argument("--saves-dirs", nargs="+", help="Optional list of directories to scan (overrides WATCH_SAVES_DIRS).")
    parser.add_argument("--out-decoded", default=str(default_decoded_dir()), help="Where decoded JSON files go.")
    parser.add_argument("--since-days", type=int, help=f"Only include files modified in the last N days (default {DEFAULT_DAYS}).")
    parser.add_argument("--since-date", help="Only include files modified on/after this ISO date (YYYY-MM-DD).")
    parser.add_argument("--no-age-filter", action="store_true", help="Disable the recent-only filter (process everything).")
    parser.add_argument("--decode", action="store_true", help="Decode HG->JSON using nmssavetool for selected files.")
    parser.add_argument("--decoder", help="Path to nmssavetool OR nmssavetool.py; overrides NMSSAVETOOL in .env if set.")
    parser.add_argument("--manifest-name", default="_manifest_recent.json", help="Filename for the emitted manifest JSON.")
    parser.add_argument("--dry-run", action="store_true", help="List actions without performing them.")
    args = parser.parse_args()

    decoder_hint = args.decoder or env.get("NMSSAVETOOL")

    # Determine input universe
    input_paths: List[str] = []
    if args.initial:
        input_paths = [args.initial]
    elif args.saves_dirs:
        input_paths = args.saves_dirs
    else:
        input_paths = split_dirs(env.get("WATCH_SAVES_DIRS", ""))

    if not input_paths:
        raise SystemExit("[ERR] No input provided. Set --initial / --saves-dirs or WATCH_SAVES_DIRS in .env")

    # Expand sources into file/dir sets
    json_inputs: List[Path] = []
    hg_dirs: List[str] = []

    for p in input_paths:
        P = Path(p).expanduser()
        if P.is_file():
            if P.suffix.lower() == ".json":
                json_inputs.append(P)
            elif P.suffix.lower() == ".hg":
                hg_dirs.append(str(P.parent))
            else:
                raise SystemExit(f"[ERR] Unsupported file type: {P}")
        elif P.is_dir():
            hg_dirs.append(str(P))
        else:
            print(f"[WARN] Ignoring non-existent path: {P}")

    # Age cutoff
    cutoff_ts = float("-inf") if args.no_age_filter else cutoff_from_args(args.since_days, args.since_date)

    # Collect HG files (recent-first)
    kept_hg, skipped_hg = iter_recent_files(hg_dirs, cutoff_ts, exts=(".hg",))

    # Report plan
    print(f"[INFO] Age filter: {'DISABLED (all files)' if args.no_age_filter else 'Enabled'}")
    if not args.no_age_filter:
        print(f"[INFO] Cutoff: {fmt_age(cutoff_ts)}")

    if kept_hg:
        print(f"[OK] {len(kept_hg)} recent .hg files selected:")
        for p in kept_hg:
            root = infer_save_root(p)
            print("   ", p, f"(root {root}; mtime {fmt_age(p.stat().st_mtime)})")
    else:
        print("[OK] No recent .hg files found under provided dirs.")

    if skipped_hg:
        print(f"[INFO] {len(skipped_hg)} .hg files skipped as older than cutoff.")

    # Include any explicit JSON inputs (they bypass age filter by design)
    if json_inputs:
        print(f"[OK] {len(json_inputs)} explicit JSON file(s) provided (age filter not applied to explicit JSON):")
        for j in json_inputs:
            print("   ", j)

    out_decoded = Path(args.out_decoded).expanduser().resolve()
    ensure_dir(out_decoded)

    if args.dry_run:
        print("[DRY-RUN] Stopping before decode/import.")
        return

    manifest: list[dict] = []

    # Optional decode phase
    if args.decode and kept_hg:
        for src in kept_hg:
            out_json = out_decoded / (src.stem + ".json")
            print(f"[decode] {src} -> {out_json}")
            run_nmssavetool(src, out_json, decoder_hint)

            record = {
                "source_path": str(src),
                "save_root": infer_save_root(src),
                "source_mtime": datetime.fromtimestamp(src.stat().st_mtime).isoformat(),
                "decoded_mtime": datetime.utcnow().isoformat(),
                "out_json": str(out_json),
                "json_sha256": sha256_file(out_json),
                "decoder_used": decoder_hint or "nmssavetool (PATH)"
            }
            manifest.append(record)

    # Write manifest if we decoded anything
    if args.decode and manifest:
        meta = {
            "generated_at": datetime.utcnow().isoformat(),
            "cutoff": (None if args.no_age_filter else fmt_age(cutoff_ts)),
            "recent_only": (not args.no_age_filter),
            "items": manifest
        }
        manifest_path = out_decoded / args.manifest_name
        manifest_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        print(f"[info] Wrote manifest: {manifest_path}")

    print("[DONE] initial selection (and optional decode) complete.")


if __name__ == "__main__":
    main()
