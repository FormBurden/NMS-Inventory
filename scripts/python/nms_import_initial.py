# nms_import_initial.py
import json, argparse, pathlib
from datetime import datetime
import pymysql

def _slots(inv):
    for s in (inv or {}).get("Slots", []) or []:
        t = (s.get("Type") or {}).get("InventoryType")
        yield {
            "resource_type": t,                       # Product | Substance | Technology
            "resource_id": s.get("Id"),
            "amount": s.get("Amount"),               # may be -1 for tech modules
            "max_amount": s.get("MaxAmount"),
            "slot_x": (s.get("Index") or {}).get("X"),
            "slot_y": (s.get("Index") or {}).get("Y"),
        }

def _push(rows, owner_type, subinv, owner_index, owner_name, inv):
    for r in _slots(inv):
        rows.append({
            "owner_type": owner_type,
            "owner_index": owner_index,
            "owner_name": owner_name or "",
            "inventory": subinv,                     # GENERAL | TECHONLY | CARGO
            **r
        })

def import_initial(save_path, db_host, db_name, db_user, db_pass, snapshot_ts=None):
    p = pathlib.Path(save_path)
    if snapshot_ts is None:
        snapshot_ts = datetime.fromtimestamp(p.stat().st_mtime)

    game = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    ctx  = (game.get("BaseContext") or {})
    psd  = (ctx.get("PlayerStateData") or {})

    rows = []

    # PLAYER
    for key, sub in (("Inventory","GENERAL"), ("Inventory_TechOnly","TECHONLY"), ("Inventory_Cargo","CARGO")):
        inv = psd.get(key)
        if isinstance(inv, dict) and isinstance(inv.get("Slots"), list):
            _push(rows, "PLAYER", sub, None, "", inv)

    # WEAPON (multitool)
    winv = psd.get("WeaponInventory")
    if isinstance(winv, dict) and isinstance(winv.get("Slots"), list):
        _push(rows, "WEAPON", "GENERAL", None, "", winv)

    # SHIPS
    for ship in psd.get("ShipOwnership", []) or []:
        name = (ship.get("Name") or "").strip()
        for key, sub in (("Inventory","GENERAL"), ("Inventory_TechOnly","TECHONLY"), ("Inventory_Cargo","CARGO")):
            inv = ship.get(key)
            if isinstance(inv, dict) and isinstance(inv.get("Slots"), list):
                _push(rows, "SHIP", sub, None, name, inv)

    # VEHICLES
    for veh in psd.get("VehicleOwnership", []) or []:
        inv  = veh.get("Inventory")
        name = (veh.get("Name") or "").strip()
        if isinstance(inv, dict) and isinstance(inv.get("Slots"), list):
            _push(rows, "VEHICLE", "GENERAL", None, name, inv)

    # FREIGHTER
    for key in ("FreighterInventory", "FreighterCargoInventory"):
        inv = ctx.get(key)
        if isinstance(inv, dict) and isinstance(inv.get("Slots"), list):
            _push(rows, "FREIGHTER", "GENERAL", None, "", inv)

    # STORAGE: only add if you actually parse storage containers (not present in your save)

    conn = pymysql.connect(host=db_host, user=db_user, password=db_pass, database=db_name,
                           autocommit=False, charset="utf8mb4")
    sql = """
    INSERT INTO nms_initial_items
      (snapshot_ts, owner_type, owner_index, owner_name,
       inventory, slot_x, slot_y, resource_id, resource_type,
       amount, max_amount, source_file)
    VALUES
      (%(snapshot_ts)s, %(owner_type)s, %(owner_index)s, %(owner_name)s,
       %(inventory)s, %(slot_x)s, %(slot_y)s, %(resource_id)s, %(resource_type)s,
       %(amount)s, %(max_amount)s, %(source_file)s)
    ON DUPLICATE KEY UPDATE
       amount=VALUES(amount),
       max_amount=VALUES(max_amount),
       source_file=VALUES(source_file);
    """
    try:
        with conn.cursor() as cur:
            payload = []
            for r in rows:
                payload.append({
                    "snapshot_ts": snapshot_ts,
                    "owner_type": r["owner_type"],
                    "owner_index": r["owner_index"],
                    "owner_name": r["owner_name"],
                    "inventory": r["inventory"],
                    "slot_x": r["slot_x"],
                    "slot_y": r["slot_y"],
                    "resource_id": r["resource_id"],
                    "resource_type": r["resource_type"],
                    "amount": r["amount"],
                    "max_amount": r["max_amount"],
                    "source_file": str(p),
                })
            if payload:
                cur.executemany(sql, payload)
        conn.commit()
    finally:
        conn.close()

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Import initial NMS inventory snapshot")
    ap.add_argument("--initial", required=True, help="Path to save2.cleaned.json")
    ap.add_argument("--db-host", default="127.0.0.1")
    ap.add_argument("--db-name", required=True)
    ap.add_argument("--db-user", required=True)
    ap.add_argument("--db-pass", required=True)
    ap.add_argument("--snapshot-ts", default=None, help="Override snapshot timestamp (YYYY-MM-DD HH:MM:SS)")
    args = ap.parse_args()

    ts = None
    if args.snapshot_ts:
        ts = datetime.fromisoformat(args.snapshot_ts)

    import_initial(args.initial, args.db_host, args.db_name, args.db_user, args.db_pass, ts)
