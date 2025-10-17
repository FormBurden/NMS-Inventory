#!/usr/bin/env python3
"""
Generate initial INSERT statements for nms_snapshots from a manifest JSON.

- Never emit empty strings for DATETIME columns.
- Derive decoded_mtime from the decoded JSON file's mtime (UTC).
- Derive json_sha256 from the decoded JSON file contents.
- Use manifest-provided source_mtime when present; else fall back:
  decoded file mtime -> current UTC time.
- Accept both "flat" manifest shape and "items" array manifests.

Usage:
  python3 scripts/python/db_import_initial.py --manifest storage/decoded/_manifest_recent.json \
    | mariadb -u nms_user -p -D nms_database -N -e
"""

import argparse
import json
import os
import sys
import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

def _utc_dt_from_epoch(epoch: int) -> str:
    """Return 'YYYY-MM-DD HH:MM:SS' in UTC for given epoch seconds."""
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def _utc_dt_from_path(path: str) -> Optional[str]:
    """Return UTC datetime string from file mtime, or None if not available."""
    try:
        st = os.stat(path)
        return _utc_dt_from_epoch(int(st.st_mtime))
    except Exception:
        return None

def _sha256_file(path: str) -> Optional[str]:
    """Return hex sha256 of file contents, or None if unreadable."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None

def _coalesce_datetime(*values: Optional[str]) -> str:
    """
    Return the first non-empty DATETIME string from values; if all are None/empty,
    return current UTC as a DATETIME string. Ensures we never emit '' for DATETIME.
    """
    for v in values:
        if v and v.strip():
            return v.strip()
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def _escape_sql(s: str) -> str:
    """Escape single quotes for SQL single-quoted strings."""
    return s.replace("'", "''")

def _iter_manifest_items(doc: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """
    Support either:
      - flat doc with keys: source_path, out_json, source_mtime, ...
      - array doc with key "items": [ {source_path, out_json, ...}, ... ]
    """
    items = doc.get("items")
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                yield it
    else:
        yield doc

def _pick_decoded_path(item: Dict[str, Any]) -> str:
    """
    Prefer 'out_json' when provided; fall back to 'source_path'.
    Many pipelines use 'source_path' == decoded JSON (e.g., storage/decoded/save2.json).
    """
    out_json = item.get("out_json")
    if isinstance(out_json, str) and out_json.strip():
        return out_json
    sp = item.get("source_path", "")
    return sp

def _extract_save_root(item: Dict[str, Any]) -> str:
    """
    Best-effort save_root:
      1) item['save_root'] if present,
      2) env NMS_SAVE_ROOT basename if set,
      3) else '' (DB may backfill later).
    """
    sr = item.get("save_root")
    if isinstance(sr, str) and sr.strip():
        return sr.strip()
    env_sr = (os.environ.get("NMS_SAVE_ROOT") or "").strip()
    if env_sr:
        try:
            stem = os.path.basename(env_sr.rstrip("/"))
            if stem:
                return stem
        except Exception:
            pass
    return ""

def _normalize_source_mtime(item: Dict[str, Any], decoded_path: str) -> str:
    """
    Ensure a concrete UTC DATETIME string for source_mtime.
    Order of precedence:
      1) item['source_mtime'] (already ISO string from build_manifest.py),
      2) decoded file mtime,
      3) current UTC time.
    """
    m = item.get("source_mtime")
    m_str = (m or "").strip() if isinstance(m, str) else ""
    if m_str:
        s = m_str.replace("T", " ").split(".", 1)[0]
        s = re.sub(r"[+-]\d{2}:\d{2}$", "", s).strip()
        return s
    return _coalesce_datetime(_utc_dt_from_path(decoded_path))


def _compose_insert_stmt(
    source_path: str, save_root: str, source_mtime: str, decoded_mtime: str, json_sha256: str
) -> str:
    """
    Produce a single INSERT ... ON DUPLICATE KEY UPDATE statement.
    All values are safe, non-empty strings at this point.
    """
    sp = _escape_sql(source_path)
    sr = _escape_sql(save_root)
    sm = _escape_sql(source_mtime)
    dm = _escape_sql(decoded_mtime)
    sh = _escape_sql(json_sha256)

    return (
        "INSERT INTO nms_snapshots "
        "(source_path, save_root, source_mtime, decoded_mtime, json_sha256) "
        f"VALUES ('{sp}', '{sr}', '{sm}', '{dm}', '{sh}') "
        "ON DUPLICATE KEY UPDATE "
        "snapshot_id = LAST_INSERT_ID(snapshot_id), "
        "decoded_mtime = VALUES(decoded_mtime), "
        "json_sha256 = VALUES(json_sha256);"
    )

def build_rows_from_manifest(doc: Dict[str, Any]):
    """
    Yield INSERT statements derived from the manifest.
    Ensures source_mtime/decoded_mtime/json_sha256 are never empty strings.
    """
    for item in _iter_manifest_items(doc):
        source_path = str(item.get("source_path") or "").strip()
        decoded_path = (_pick_decoded_path(item) or "").strip() or source_path

        # Guard: ensure we have at least a source_path; else skip
        if not source_path:
            continue

        save_root = _extract_save_root(item)
        source_mtime = _normalize_source_mtime(item, decoded_path)
        decoded_mtime = _coalesce_datetime(_utc_dt_from_path(decoded_path))

        sha = _sha256_file(decoded_path) or _sha256_file(source_path) or ""
        if not sha:
            # if we can't hash the file, keep a stable non-empty marker to avoid ''
            sha = "0" * 64

        yield _compose_insert_stmt(
            source_path=source_path,
            save_root=save_root,
            source_mtime=source_mtime,
            decoded_mtime=decoded_mtime,
            json_sha256=sha,
        )

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Emit INSERTs for nms_snapshots from manifest")
    ap.add_argument("--manifest", required=True, help="Path to manifest JSON")
    args = ap.parse_args(argv)

    try:
        with open(args.manifest, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except Exception as e:
        print(f"-- FATAL: unable to read manifest {args.manifest}: {e}", file=sys.stderr)
        return 2

    any_rows = False
    for sql in build_rows_from_manifest(doc):
        any_rows = True
        print(sql)

    if not any_rows:
        # still produce a harmless SELECT to keep the pipeline from being 'empty'
        print("SELECT 'no snapshot rows generated' AS info;")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
