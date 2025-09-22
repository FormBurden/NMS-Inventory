from __future__ import annotations
import json, os, re
from typing import Any, Dict, List, Tuple
from .text import strip_control_codes

Json = Any
Path = Tuple[str, ...]

def save_json(path: str, obj: Json, pretty: bool = True) -> None:
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        if pretty:
            json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=False)
        else:
            json.dump(obj, fh, ensure_ascii=False, separators=(',', ':'))

def ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)

def flatten_leaves(obj: Json, prefix: Path = ()) -> List[Tuple[Path, Any]]:
    """Return list of (path, value) for scalar leaves (str/num/bool/None)."""
    out: List[Tuple[Path, Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(flatten_leaves(v, prefix + (str(k),)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(flatten_leaves(v, prefix + (str(i),)))
    else:
        out.append((prefix, obj))
    return out

def deep_map(obj: Json, fn):
    """Recursively apply fn to scalar values (str/num/bool/None)."""
    if isinstance(obj, dict):
        return {k: deep_map(v, fn) for k, v in obj.items()}
    if isinstance(obj, list):
        return [deep_map(v, fn) for v in obj]
    return fn(obj)

def clean_strings(obj: Json) -> Json:
    """Strip control codes from every string in the JSON."""
    def _f(v):
        if isinstance(v, str):
            return strip_control_codes(v)
        return v
    return deep_map(obj, _f)

# ---- tolerant JSON loader helpers -----------------------------------------

_BACKSLASH_FIX = re.compile(r'\\(?!["\\/bfnrtu])')

def _relax_text(text: str) -> str:
    # Strip UTF-8 BOM if present
    if text.startswith('\ufeff'):
        text = text[1:]
    # Duplicate any invalid backslash escape so it becomes a literal backslash
    # e.g., "\#" -> "\\#"
    text = _BACKSLASH_FIX.sub(r'\\\\', text)
    return text

def load_json(path: str) -> Json:
    """
    Tolerant loader:
    - first try strict json.loads
    - then try parsing first top-level object via raw_decode (handles 'Extra data')
    - then try 'relaxed' text (fix invalid backslashes) + strict
    - finally 'relaxed' + raw_decode
    """
    with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
        text = fh.read()

    # 1) strict
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2) strict first-object only
    dec = json.JSONDecoder()
    try:
        obj, _end = dec.raw_decode(text.lstrip())
        return obj
    except Exception:
        pass

    # 3) relaxed strict
    text2 = _relax_text(text)
    try:
        return json.loads(text2)
    except json.JSONDecodeError:
        pass

    # 4) relaxed first-object only
    try:
        obj, _end = dec.raw_decode(text2.lstrip())
        return obj
    except Exception as e:
        # Last resort: re-raise the original error to show the file/position
        raise

def deep_rename_keys(obj: Json, mapping: Dict[str, str]) -> Json:
    """
    Rename dict keys recursively using the provided mapping (last-segment only).
    Lists are traversed; scalars are returned unchanged.
    """
    if isinstance(obj, dict):
        return { mapping.get(k, k): deep_rename_keys(v, mapping) for k, v in obj.items() }
    if isinstance(obj, list):
        return [deep_rename_keys(v, mapping) for v in obj]
    return obj
