from __future__ import annotations
from typing import Any, Dict, List, Tuple, Union
from scripts.python.utils.paths import get_at_path, parse_path_string

Json = Any
PathStr = str

# Category hints (used only if no explicit mapping covers a parent)
CATS = (
    ("Exosuit",  ("suit","exo","exosuit")),
    ("Ship",     ("ship","starship","fighter","shuttle","hauler","exotic","solar","interceptor","living")),
    ("MultiTool",("multitool","multi","weapon","tool")),
    ("Freighter",("freighter","capital","carrier")),
    ("Exocraft", ("vehicle","exocraft","minotaur","mech","nautilon","roamer","nomad","colossus","pilgrim","bike")),
    ("Storage",  ("storage","container","chest","vault","wardrobe")),
)

# Slot list bounds seen in your reports
MIN_SLOTS = 5
MAX_SLOTS = 120

# Keys that strongly suggest non-inventory arrays
NON_INV_KEYS = {"Position","ObjectID","GalacticAddress","Timestamp","UserData"}

# Keys that suggest actual item slots
INV_KEYS = {"Id","Amount","Value"}

def _guess_category_from_path(path: str) -> str:
    p = path.lower()
    for name, needles in CATS:
        if any(n in p for n in needles):
            return name
    return "Storage"

def _parent_path_str(path_str: str) -> str:
    toks: List[str] = []
    cur = ""; esc = False
    for ch in path_str:
        if ch == "\\":
            esc = not esc; cur += ch; continue
        if ch == "." and not esc:
            toks.append(cur); cur = ""
        else:
            cur += ch
        esc = False
    if cur: toks.append(cur)
    return ".".join(toks[:-1]) if len(toks) > 1 else (toks[0] if toks else "")

def _slot_keys(node: Any) -> set:
    if isinstance(node, list) and node and isinstance(node[0], dict):
        return set(node[0].keys())
    return set()

def _is_inventory_slot_list(node: Any) -> bool:
    if not (isinstance(node, list) and node and all(isinstance(x, dict) for x in node)):
        return False
    n = len(node)
    if n < MIN_SLOTS or n > MAX_SLOTS:
        return False
    keys = _slot_keys(node)
    if keys & NON_INV_KEYS:
        return False
    if not (keys & INV_KEYS):
        return False
    return True

def compute_inventory_rollup(
    data: Json,
    index: Dict[str, List[PathStr]],
    categories: Dict[str, str] | None = None,
    child_types: Dict[str, str] | None = None
) -> Dict[str, Any]:
    """
    Group leaf slot-array paths by their parent (container object).
    Count each parent as one container only if it owns 1..3 plausible slot arrays.
    Accept child arrays that either look like item slots OR are explicitly tagged
    in child_types (allowing obfuscated tech/cargo pages).
    Distribute per child using child_types mapping: child_path -> general|tech|cargo.
    """
    categories = categories or {}
    child_types = child_types or {}

    inv_paths = index.get("inventories", []) or []
    by_parent: Dict[str, List[str]] = {}
    for s in inv_paths:
        parent = _parent_path_str(s)
        if not parent:
            continue
        by_parent.setdefault(parent, []).append(s)

    totals = {"containers": 0, "general": 0, "tech": 0, "cargo": 0, "total": 0}
    by_cat: Dict[str, Dict[str,int]] = {}

    for parent, children in by_parent.items():
        good_children: List[str] = []
        for s in children:
            node = get_at_path(data, parse_path_string(s))
            ok = _is_inventory_slot_list(node)
            # If the child is explicitly tagged, allow it when length looks plausible
            if not ok and s in child_types and isinstance(node, list) and MIN_SLOTS <= len(node) <= MAX_SLOTS:
                ok = True
            if ok:
                good_children.append(s)

        # Require a natural inventory shape (1..3 lists)
        if not (1 <= len(good_children) <= 3):
            continue

        # Sum with per-child type assignment
        g = t = c = 0
        for s in good_children:
            node = get_at_path(data, parse_path_string(s))
            n = len(node)
            bucket = (child_types.get(s) or "general").lower()
            if bucket == "tech": t += n
            elif bucket == "cargo": c += n
            else: g += n

        tot = g + t + c
        if tot == 0:
            continue

        cat = categories.get(parent) or _guess_category_from_path(parent)
        b = by_cat.setdefault(cat, {"containers": 0, "general": 0, "tech": 0, "cargo": 0, "total": 0})
        b["containers"] += 1
        b["general"]    += g
        b["tech"]       += t
        b["cargo"]      += c
        b["total"]      += tot

        totals["containers"] += 1
        totals["general"]    += g
        totals["tech"]       += t
        totals["cargo"]      += c
        totals["total"]      += tot

    # Ensure stable keys for UI
    for name, _ in CATS:
        by_cat.setdefault(name, {"containers": 0, "general": 0, "tech": 0, "cargo": 0, "total": 0})

    return {
        "by_category": by_cat,
        "totals": totals,
    }
