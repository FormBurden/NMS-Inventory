from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

Json = Any
Path = Tuple[Union[str,int], ...]

def walk_with_path(obj: Json, path: Path = ()):
    """Yield (path, value). Includes containers and leaves."""
    yield path, obj
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_with_path(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_with_path(v, path + (i,))

def get_at_path(obj: Json, path: Path) -> Any:
    cur = obj
    for p in path:
        if isinstance(cur, dict) and isinstance(p, str):
            cur = cur.get(p)
        elif isinstance(cur, list) and isinstance(p, int) and 0 <= p < len(cur):
            cur = cur[p]
        else:
            return None
    return cur

def path_to_string(path: Path) -> str:
    """Turn a path into a printable string. Escapes dots in keys."""
    out: List[str] = []
    for p in path:
        if isinstance(p, int):
            out.append(f"[{p}]")
        else:
            out.append(p.replace(".", "\\."))
    return ".".join(out)

def parse_path_string(s: str) -> Path:
    """Parse the printed path back into a tuple path."""
    parts: List[Union[str,int]] = []
    tokens: List[str] = []
    cur = ""
    esc = False
    for ch in s:
        if ch == "\\":
            esc = not esc
            cur += ch
            continue
        if ch == "." and not esc:
            tokens.append(cur); cur = ""
        else:
            cur += ch
        esc = False
    if cur: tokens.append(cur)

    for tok in tokens:
        if tok.endswith("]") and "[" in tok:
            base, idx = tok.rsplit("[", 1)
            base = base.replace("\\.", ".")
            if base: parts.append(base)
            parts.append(int(idx[:-1]))
        else:
            parts.append(tok.replace("\\.", "."))
    return tuple(parts)  # type: ignore

def find_first_scalar(obj: Json, keys: Iterable[str]) -> Optional[Any]:
    """Find first scalar value by any key name (case-insensitive)."""
    keys_lc = {k.lower() for k in keys}
    for (path, val) in walk_with_path(obj):
        if not path: continue
        parent = get_at_path(obj, path[:-1])
        last = path[-1]
        if isinstance(parent, dict) and isinstance(last, str):
            if last.lower() in keys_lc and not isinstance(val, (dict, list)):
                return val
    return None

def has_key(obj: Json, key: str) -> bool:
    kl = key.lower()
    for (path, _val) in walk_with_path(obj):
        if not path: continue
        parent = get_at_path(obj, path[:-1])
        last = path[-1]
        if isinstance(parent, dict) and isinstance(last, str) and last.lower() == kl:
            return True
    return False
