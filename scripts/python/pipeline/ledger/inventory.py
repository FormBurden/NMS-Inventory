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

def aggregate_inventory(js: Dict[str, Any], include_tech: bool = False) -> Dict[Tuple[str, str], int]:
    # Flattens the whole save json into {(owner_type,id): total_amount}
    # include_tech: include Tech slots (if false, only Items+Cargo)
    totals: Dict[Tuple[str, str], int] = {}
    for owner in js.get("Owners", []):
        if not isinstance(owner, dict):
            continue
        owner_type = _inventory_type(owner)
        inv = owner.get("Inventory", {})
        for rec in _slot_records_from_inventory(owner_type, inv):
            if not include_tech and rec["section"] == "tech":
                continue
            key = (rec["owner_type"], rec["id"])
            totals[key] = totals.get(key, 0) + int(rec["amount"] or 0)
    return totals
