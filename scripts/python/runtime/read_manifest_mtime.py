#!/usr/bin/env python3
# Read the raw-save mtime from a decode/manifest JSON and print it as epoch seconds.
# Accepts multiple shapes:
# - Top-level: {"source_mtime": "..."} OR {"mtime": "..."}  (string or seconds)
# - Nested:    {"items":[{"source_mtime":"...", "source_path":"..."}]}
#
# If the value is a digit-like string, print it directly.
# If it's a timestamp string (e.g. "YYYY-MM-DD HH:MM:SS"), convert to epoch seconds
# using the *local timezone* of the running system.
# As a robust fallback (when only a decoded JSON path is present), we attempt to
# stat() the raw HG via items[0].hg_path if present; otherwise we leave empty.

import sys, json, os, time

TOP_KEYS = ("source_mtime", "src_mtime", "sourceMtime", "sourceMTime", "mtime")

def _to_epoch_seconds(s: str) -> str:
    s = str(s).strip()
    if not s:
        return ""
    # Already numeric?
    if s.isdigit():
        return s
    # Try common "YYYY-MM-DD HH:MM:SS" with local time
    try:
        tm = time.strptime(s, "%Y-%m-%d %H:%M:%S")
        return str(int(time.mktime(tm)))
    except Exception:
        return ""

def _from_top_level(doc: dict) -> str:
    for k in TOP_KEYS:
        if k in doc:
            return _to_epoch_seconds(doc[k])
    return ""

def _from_nested_items(doc: dict) -> str:
    items = doc.get("items")
    if not isinstance(items, list) or not items:
        return ""
    it0 = items[0]
    # Prefer the explicit raw-save timestamp if present
    for k in TOP_KEYS:
        if k in it0:
            s = _to_epoch_seconds(it0[k])
            if s:
                return s
    # Nothing parseable; best-effort fallback: if an HG path is given, stat it.
    # Some pipelines store hg_path; if not present, we can't do better here.
    hg_path = it0.get("hg_path")
    if isinstance(hg_path, str) and os.path.isfile(hg_path):
        try:
            return str(int(os.path.getmtime(hg_path)))
        except Exception:
            pass
    return ""

def main():
    if len(sys.argv) < 2:
        return 0
    p = sys.argv[1]
    try:
        with open(p, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except Exception:
        return 0

    # 1) Try top-level keys first
    out = _from_top_level(doc)
    if not out:
        # 2) Try nested manifest shape
        out = _from_nested_items(doc)

    if out:
        print(out)
    # else: print nothing (caller treats empty as "unknown")

if __name__ == "__main__":
    main()
