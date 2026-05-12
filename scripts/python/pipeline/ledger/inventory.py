# scripts/python/pipeline/ledger/inventory.py
from typing import Any, Dict, Iterable, List, Tuple, Optional
import re

GOOD_TYPES = {"Substance", "Product", "Technology"}
SANE_CAPS = {50, 100, 101, 200, 250, 500, 801, 1000, 1001, 2000, 9999}


def _norm_key(s: str) -> str:
    return (s or "").strip().lower().replace(" ", "_")


def _inventory_type(owner_js: Dict[str, Any]) -> str:
    for k in ("Character", "Ship", "Freighter", "Vehicle", "Storage", "Base"):
        if k in owner_js:
            return _norm_key(k)
    return "unknown"


def _dict_get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default


def _is_progress_token(rid: str) -> bool:
    if not rid or not isinstance(rid, str):
        return False
    if not rid.startswith("^"):
        return False
    stem = rid[1:]
    bad_prefixes = ("SMUGGLE_", "FLYER", "BIGGS_", "POLICE_", "GET_")
    if any(stem.startswith(p) for p in bad_prefixes):
        return True
    return len(stem) >= 4 and stem[0] == "S" and stem[1].isdigit() and stem[2].isdigit() and stem[3] == "_"


def _is_obfuscated_item_slot(slot: Dict[str, Any]) -> bool:
    rid = slot.get("b2n")
    amount = slot.get("1o9")
    cap = slot.get("F9q")
    item_type = _dict_get(slot.get("Vn8"), "elv")
    if not isinstance(rid, str) or not rid.startswith("^"):
        return False
    if not isinstance(item_type, str) or item_type not in GOOD_TYPES:
        return False
    if not isinstance(amount, int) or not isinstance(cap, int):
        return False
    if amount < 0:
        return False
    if cap not in SANE_CAPS and amount > cap and amount >= 9999:
        return False
    return True


def _is_readable_item_slot(slot: Dict[str, Any]) -> bool:
    return isinstance(slot, dict) and "Id" in slot and "Amount" in slot


def _is_item_slot(slot: Dict[str, Any]) -> bool:
    return isinstance(slot, dict) and (_is_readable_item_slot(slot) or _is_obfuscated_item_slot(slot))


def _slot_id(slot: Dict[str, Any]) -> Optional[str]:
    rid = slot.get("Id")
    if rid is None:
        rid = slot.get("b2n")
    if rid is None:
        return None
    rid_s = str(rid)
    if _is_progress_token(rid_s):
        return None
    return rid_s


def _slot_item_type(slot: Dict[str, Any]) -> str:
    item_type = _dict_get(slot.get("Vn8"), "elv")
    if isinstance(item_type, str):
        return item_type.strip()

    item_type = slot.get("Type")
    if isinstance(item_type, str):
        return item_type.strip()

    item_type = slot.get("ItemType")
    if isinstance(item_type, str):
        return item_type.strip()

    return ""


def _slot_amount(slot: Dict[str, Any]) -> int:
    if "Amount" in slot:
        try:
            return int(slot.get("Amount") or 0)
        except Exception:
            return 0

    amount = slot.get("1o9")
    cap = slot.get("F9q")
    candidates = [x for x in (amount, cap) if isinstance(x, int) and x > 0]
    if isinstance(amount, int) and isinstance(cap, int) and cap in SANE_CAPS and amount <= cap:
        return amount
    if candidates:
        return int(min(candidates))
    return 0


def _slot_records_from_inventory(owner_type: str, inv: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for section in ("Items", "Tech", "Cargo"):
        slots = inv.get(section)
        if isinstance(slots, list):
            for sl in slots:
                if _is_item_slot(sl):
                    yield {
                        "owner_type": owner_type,
                        "section": _norm_key(section),
                        "id": _slot_id(sl),
                        "amount": _slot_amount(sl),
                        "seed": sl.get("Seed"),
                    }


def _resolve_selector(root: Dict[str, Any], sel: str) -> Any:
    cur: Any = root
    for seg in sel.split("."):
        while True:
            m = re.match(r"^(.*?)(\[\d+\])(.*)$", seg)
            if m:
                pre, idxs, post = m.group(1), m.group(2), m.group(3)
                if pre:
                    cur = cur[pre]
                cur = cur[int(idxs[1:-1])]
                seg = post
                if not seg:
                    break
            else:
                if seg:
                    cur = cur[seg]
                break
    return cur


def _infer_section_from_selector(sel: str) -> str:
    if sel.endswith(".MMm") or ".MMm" in sel:
        return "cargo"
    if sel.endswith(".hl?") or ".hl?" in sel:
        return "tech"
    if ".PMT." in sel and not sel.endswith(".hl?"):
        return "cargo"
    return "general"


def _infer_section_from_slot(slot: Dict[str, Any], fallback: str) -> str:
    item_type = _slot_item_type(slot).lower()
    if item_type == "technology":
        return "tech"

    if _is_readable_item_slot(slot):
        return fallback

    grid = _dict_get(slot, "3ZH", {})
    qh = _dict_get(grid, ">Qh")
    xj = _dict_get(grid, "XJ>")
    amount = _slot_amount(slot)
    if amount > 500:
        return "cargo"
    if isinstance(qh, int) and isinstance(xj, int):
        if qh >= 5 or xj >= 2:
            return "cargo"
    return "general"


def _infer_owner_from_selector(sel: str) -> str:
    parts = set(seg for seg in re.split(r"\.|\[\d+\]", sel) if seg)
    if "<IP" in parts or "0wS" in parts or "FdP" in parts:
        return "freighter"
    if "8ZP" in parts:
        return "vehicle"
    if "3Nc" in parts:
        return "storage"
    if "P;m" in parts:
        return "ship"
    if ";l5" in parts:
        return "character"

    root = sel.split(".", 1)[0]
    if root == "2YS":
        return "ship"
    if root == "vLc":
        return "character"
    if root == "3Nc":
        return "storage"

    return "unknown"


def _path_has_bad_context(path: List[Any]) -> bool:
    for seg in path:
        if isinstance(seg, str) and seg in {"RQA", "b69", "JWK"}:
            return True
    return False


def _infer_owner_from_path(path: List[Any]) -> str:
    segs = {str(p) for p in path if isinstance(p, str)}
    if ";l5" in segs:
        return "character"
    if "P;m" in segs:
        return "ship"
    if "<IP" in segs or "0wS" in segs or "FdP" in segs:
        return "freighter"
    if "8ZP" in segs:
        return "vehicle"
    if "3Nc" in segs:
        return "storage"

    pstr = ".".join(str(p) for p in path[-256:])
    if ".;l5." in pstr:
        return "character"
    if ".P;m." in pstr:
        return "ship"
    if ".<IP." in pstr or ".0wS." in pstr or ".FdP." in pstr:
        return "freighter"
    if ".8ZP." in pstr:
        return "vehicle"
    if ".3Nc." in pstr:
        return "storage"

    return "unknown"


def _walk_dicts(obj: Any) -> Iterable[Tuple[List[Any], Dict[str, Any]]]:
    stack: List[Tuple[List[Any], Any]] = [([], obj)]
    while stack:
        path, val = stack.pop()
        if isinstance(val, dict):
            yield path, val
            for k, v in val.items():
                stack.append((path + [k], v))
        elif isinstance(val, list):
            for i, v in enumerate(val):
                stack.append((path + [i], v))


def _base_resource_id(rid: str) -> str:
    base = str(rid or "").strip().upper().lstrip("^")
    hash_pos = base.find("#")
    if hash_pos >= 0:
        base = base[:hash_pos]
    return base


def _owner_from_resource_id(rid: str) -> str:
    base = _base_resource_id(rid)

    if (
        base.startswith("F_")
        or base.startswith("FREI_")
        or base.startswith("FRIG_")
        or base.startswith("MAINT_FRIG")
    ):
        return "freighter"

    if (
        base.startswith("VEHICLE_")
        or base.startswith("MECH_")
        or base.startswith("SUB_")
        or base.startswith("NAUT_")
        or base == "FISH_SKIFF"
    ):
        return "vehicle"

    if (
        base.startswith("CV_")
        or base.startswith("SHIP")
        or base.startswith("HDRIVE")
        or base.startswith("LAUNCHER")
        or base.startswith("HYPERDRIVE")
        or base.startswith("WARP")
        or base.startswith("UT_SHIP")
        or base in {"UT_ROCKETS", "UT_LAUNCHCHARGE", "UT_QUICKWARP", "WATER_LANDER"}
    ):
        return "ship"

    return ""


def _add_slot(
    totals: Dict[Tuple[str, str, str], int],
    owner_type: str,
    inventory: str,
    slot: Dict[str, Any],
    include_tech: bool,
) -> None:
    if not include_tech and inventory == "tech":
        return

    rid = _slot_id(slot)
    amt = _slot_amount(slot)
    if rid is None or amt <= 0:
        return

    resource_owner = _owner_from_resource_id(rid)
    if resource_owner:
        owner_type = resource_owner

    key = (owner_type, inventory, rid)
    totals[key] = totals.get(key, 0) + amt


def aggregate_inventory(js: Dict[str, Any], include_tech: bool = False) -> Dict[Tuple[str, str, str], int]:
    """Flatten decoded or full-parse JSON into {(owner_type, inventory, resource_id): total_amount}."""
    scanned_totals: Dict[Tuple[str, str, str], int] = {}
    for path, slot in _walk_dicts(js):
        if _path_has_bad_context(path):
            continue
        if not _is_item_slot(slot):
            continue
        owner_type = _infer_owner_from_path(path)
        inventory = _infer_section_from_slot(slot, "general")
        _add_slot(scanned_totals, owner_type, inventory, slot, include_tech)

    totals: Dict[Tuple[str, str, str], int] = dict(scanned_totals)
    indexed_totals: Dict[Tuple[str, str, str], int] = {}
    idx = js.get("_index", {}).get("inventories", [])
    if not isinstance(idx, list):
        return totals

    for sel in idx:
        if not isinstance(sel, str):
            continue
        try:
            node = _resolve_selector(js, sel)
        except Exception:
            continue
        if not isinstance(node, list):
            continue

        selector_section = _infer_section_from_selector(sel)
        owner_type = _infer_owner_from_selector(sel)
        for slot in node:
            if not _is_item_slot(slot):
                continue
            inventory = _infer_section_from_slot(slot, selector_section)
            _add_slot(indexed_totals, owner_type, inventory, slot, include_tech)

    for key, amount in indexed_totals.items():
        if key not in totals:
            totals[key] = amount

    return totals