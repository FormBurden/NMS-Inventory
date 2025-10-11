from __future__ import annotations
from typing import Any, Dict, List, Tuple
from scripts.python.utils.paths import walk_with_path, get_at_path, path_to_string, parse_path_string

Json = Any
PathStr = str

def _find_all_by_key_contains(obj: Json, needles, expect_type=None) -> List[PathStr]:
    out: List[PathStr] = []
    needles_lc = [n.lower() for n in needles]
    for (path, val) in walk_with_path(obj):
        if not path: continue
        parent = get_at_path(obj, path[:-1])
        last = path[-1]
        if isinstance(parent, dict) and isinstance(last, str):
            name_lc = last.lower()
            if any(n in name_lc for n in needles_lc):
                if expect_type is None or isinstance(val, expect_type):
                    out.append(path_to_string(path))
    return out

def _dedupe(seq: List[PathStr]) -> List[PathStr]:
    seen: set[str] = set()
    out: List[str] = []
    for s in seq:
        if s in seen: continue
        out.append(s); seen.add(s)
    return out

def find_sections(data):
    """
    Build a lightweight index of interesting sections in the decoded JSON.
    For inventories, we only record LEAF lists-of-dicts with plausible slot sizes (5..120),
    never their parent dict path (avoids double-counting).
    """
    idx: Dict[str, List[str]] = {"inventories": []}

    def walk(obj: Any, path: List[Any]) -> None:
        # Dict: record child list-of-dicts that look like slot arrays, then recurse
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                    n = len(v)
                    if 5 <= n <= 120:
                        idx["inventories"].append(path_to_string(path + [k]))
            for k, v in obj.items():
                walk(v, path + [k])
            return

        # List: record itself if it's a plausible slot array, then recurse into elements
        if isinstance(obj, list):
            if obj and all(isinstance(x, dict) for x in obj):
                n = len(obj)
                if 5 <= n <= 120:
                    idx["inventories"].append(path_to_string(path))
            for i, v in enumerate(obj):
                walk(v, path + [i])
            return

        # Primitives: ignore
        return

    walk(data, [])

    # Deduplicate while keeping order
    seen = set()
    dedup = []
    for p in idx["inventories"]:
        if p not in seen:
            seen.add(p)
            dedup.append(p)
    idx["inventories"] = dedup
    return idx



    for k in list(idx.keys()):
        idx[k] = _dedupe(idx[k])
    return idx

def build_summary(data: Json, index: Dict[str, List[PathStr]]) -> Dict[str, Any]:
    summary = {
        "inventory": {"containers": 0, "total_slots": 0},
        "milestones": {"groups": 0, "items": 0},
        "bases": {"groups": 0, "items": 0},
        "teleporters": {"groups": 0, "items": 0},
        "companions": {"groups": 0, "items": 0},
    }

    inv_paths = index.get("inventories", [])
    summary["inventory"]["containers"] = len(inv_paths)
    total_slots = 0
    for s in inv_paths:
        node = get_at_path(data, parse_path_string(s))
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                    total_slots += len(v)
        elif isinstance(node, list):
            total_slots += len(node)
    summary["inventory"]["total_slots"] = total_slots

    def count_groups_items(paths: List[str]) -> Tuple[int, int]:
        g = 0; items = 0
        for s in paths:
            node = get_at_path(data, parse_path_string(s))
            if isinstance(node, list):
                g += 1; items += len(node)
        return g, items

    summary["milestones"]["groups"],  summary["milestones"]["items"]  = count_groups_items(index.get("milestones", []))
    summary["bases"]["groups"],       summary["bases"]["items"]       = count_groups_items(index.get("bases", []))
    summary["teleporters"]["groups"], summary["teleporters"]["items"] = count_groups_items(index.get("teleporter_history", []))
    summary["companions"]["groups"],  summary["companions"]["items"]  = count_groups_items(index.get("companions", []))
    return summary

def merge_sections_with_map(index: Dict[str, List[PathStr]], sections_map: Dict[str, List[PathStr]]) -> Dict[str, List[PathStr]]:
    out = {k: list(v) for k, v in index.items()}
    for k, v in sections_map.items():
        if not isinstance(v, list): continue
        out.setdefault(k, [])
        for p in v:
            if p not in out[k]:
                out[k].append(p)
    return out
