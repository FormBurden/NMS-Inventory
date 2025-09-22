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

def find_sections(obj: Json) -> Dict[str, List[PathStr]]:
    """Heuristically discover big sections. Works better after key-renaming."""
    idx: Dict[str, List[PathStr]] = {
        "inventories": [],
        "milestones": [],
        "bases": [],
        "teleporter_history": [],
        "companions": [],
        "difficulty": [],
        "season_data": [],
    }
    # Season / difficulty by name
    idx["season_data"]       = _find_all_by_key_contains(obj, ["SeasonData"], dict)
    idx["difficulty"]        = _find_all_by_key_contains(obj, ["DifficultySetting", "DifficultyPreset"], dict)
    # Milestones / bases / teleporter / companions by name
    idx["milestones"]        = _find_all_by_key_contains(obj, ["Milestone", "Journey"], list)
    idx["bases"]             = _find_all_by_key_contains(obj, ["Base", "Bases"], list)
    idx["teleporter_history"]= _find_all_by_key_contains(obj, ["Teleport", "Teleporter"], list)
    idx["companions"]        = _find_all_by_key_contains(obj, ["Companion", "Pet", "Creature"], list)

    # Inventories by shape (fallback when keys are obfuscated)
    for (path, val) in walk_with_path(obj):
        if isinstance(val, dict):
            for k, v in val.items():
                if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                    if 10 <= len(v) <= 250:
                        idx["inventories"].append(path_to_string(path))
                        break
        elif isinstance(val, list):
            if val and all(isinstance(x, dict) for x in val) and 10 <= len(val) <= 250:
                idx["inventories"].append(path_to_string(path))

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
