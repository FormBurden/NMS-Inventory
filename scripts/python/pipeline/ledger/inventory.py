# scripts/python/pipeline/ledger/inventory.py
from typing import Any, Dict, Iterable, List, Tuple, Optional

def _norm_key(s: str) -> str:
    return (s or "").strip().lower().replace(" ", "_")

def _inventory_type(owner_js: Dict[str, Any]) -> str:
    # Map owner's JSON section to a canonical type
    for k in ("Character", "Ship", "Freighter", "Vehicle", "Storage"):
        if k in owner_js:
            return _norm_key(k)
    return "unknown"

def _is_item_slot(slot: Dict[str, Any]) -> bool:
    return isinstance(slot, dict) and "Id" in slot and "Amount" in slot

def _slot_records_from_inventory(owner_type: str, inv: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    # Walk through slot arrays; emit normalized item records
    for section in ("Items", "Tech", "Cargo"):
        slots = inv.get(section)
        if isinstance(slots, list):
            for sl in slots:
                if _is_item_slot(sl):
                    yield {
                        "owner_type": owner_type,
                        "section": _norm_key(section),
                        "id": sl.get("Id"),
                        "amount": sl.get("Amount", 0),
                        "seed": sl.get("Seed"),
                    }

def aggregate_inventory(js: Dict[str, Any], include_tech: bool = False) -> Dict[Tuple[str, str, str], int]:
    """Flatten full-parse JSON into {(owner_type, inventory, resource_id): total_amount}.
    Accepts the new full-parse shape that exposes an _index.inventories selector list.
    include_tech: if False, exclude 'tech' inventory section.
    """
    totals: Dict[Tuple[str, str, str], int] = {}
    idx = js.get("_index", {}).get("inventories", [])
    if not isinstance(idx, list):
        return totals

    def _resolve_selector(root: Dict[str, Any], sel: str):
        cur: Any = root
        segs = sel.split(".")
        for seg in segs:
            # resolve any embedded [n] array steps within a single segment
            while True:
                m = __import__("re").match(r"^(.*?)(\[\d+\])(.*)$", seg)
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
        # Heuristic based on selector tokens seen in full-parse index:
        #   '.PMT.' => cargo; '.hl?' => tech; else => general
        if ".PMT." in sel:
            return "cargo"
        if ".hl?" in sel:
            return "tech"
        return "general"

    def _infer_owner_from_selector(sel: str) -> str:
        # Root token hint: '2YS' appears to be ship-related; 'vLc' suit/storage.
        root = sel.split(".")[0]
        if root == "2YS":
            return "ship"
        if root == "vLc":
            return "character"
        return "unknown"

    for sel in idx:
        try:
            node = _resolve_selector(js, sel)
        except Exception:
            continue
        if not isinstance(node, list):
            continue
        inv_section = _infer_section_from_selector(sel)
        owner_type = _infer_owner_from_selector(sel)
        for e in node:
            if not isinstance(e, dict):
                continue
            rid = e.get("Id")
            if rid is None:
                continue
            amt = int(e.get("Amount", 0) or 0)
            if not include_tech and inv_section == "tech":
                continue
            key = (owner_type, inv_section, str(rid))
            totals[key] = totals.get(key, 0) + amt
    return totals
