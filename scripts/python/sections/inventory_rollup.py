from __future__ import annotations
from typing import Any, Dict, List, Tuple
from scripts.python.utils.paths import get_at_path, parse_path_string

Json = Any
PathStr = str

CATS = (
    ("Exosuit",  ("suit","exo","exosuit")),
    ("Ship",     ("ship","starship","fighter","shuttle","hauler","exotic","solar","interceptor","living")),
    ("MultiTool",("multitool","multi","weapon","tool")),
    ("Freighter",("freighter","capital","carrier")),
    ("Exocraft", ("vehicle","exocraft","minotaur","mech","nautilon","roamer","nomad","colossus","pilgrim","bike")),
    ("Storage",  ("storage","container","chest","vault","wardrobe")),
)

def _guess_category_from_path(path: str) -> str:
    p = path.lower()
    for name, needles in CATS:
        if any(n in p for n in needles):
            return name
    # very rough fallback based on common words
    if "tech" in p: return "Exosuit"  # lots of tech arrays live under suit
    return "Storage"

def _count_slots(node: Json) -> Dict[str,int]:
    """
    Heuristic slot counter:
      - if dict: sum length of any child lists of dicts, bucket by key name
      - if list: count as 'general'
    """
    general = tech = cargo = 0
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                lk = k.lower()
                n = len(v)
                if "tech" in lk:
                    tech += n
                elif "cargo" in lk or "bag" in lk:
                    cargo += n
                else:
                    # "slots", "inventory", "main", or unknown → general
                    general += n
    elif isinstance(node, list):
        general += len(node)
    total = general + tech + cargo
    return {"general": general, "tech": tech, "cargo": cargo, "total": total}

def compute_inventory_rollup(data: Json, index: Dict[str, List[PathStr]]) -> Dict[str, Any]:
    by_cat: Dict[str, Dict[str,int]] = {}
    totals = {"containers": 0, "general": 0, "tech": 0, "cargo": 0, "total": 0}

    inv_paths = index.get("inventories", []) or []
    for s in inv_paths:
        node = get_at_path(data, parse_path_string(s))
        if node is None:
            continue
        slots = _count_slots(node)
        cat = _guess_category_from_path(s)

        b = by_cat.setdefault(cat, {"containers": 0, "general": 0, "tech": 0, "cargo": 0, "total": 0})
        b["containers"] += 1
        b["general"]    += slots["general"]
        b["tech"]       += slots["tech"]
        b["cargo"]      += slots["cargo"]
        b["total"]      += slots["total"]

        totals["containers"] += 1
        totals["general"]    += slots["general"]
        totals["tech"]       += slots["tech"]
        totals["cargo"]      += slots["cargo"]
        totals["total"]      += slots["total"]

    # always include all categories for stable UI, even if zero
    for name, _ in CATS:
        by_cat.setdefault(name, {"containers": 0, "general": 0, "tech": 0, "cargo": 0, "total": 0})

    return {
        "by_category": by_cat,
        "totals": totals,
    }
