#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
No Man's Sky Resource Ledger & Initial Import (v3)
- Ledger across JSON snapshots (with session coalescing)
- Initial "point-in-time" export to CSV/SQL or direct MariaDB insert
- NEW: Baseline from SQL dump or DB table (when you only have one new JSON)
- NEW: Optional write ledger deltas into DB

Usage examples are at the bottom of this file in the __main__ guard.
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple, Optional

# ---------------- Timestamp helpers ----------------
def parse_any_timestamp(js: Dict[str, Any]) -> Optional[dt.datetime]:
    candidates: List[str] = []
    for k in ("Timestamp", "SaveTime"):
        v = js.get(k)
        if isinstance(v, str):
            candidates.append(v)
    meta = js.get("MetaData") or js.get("metadata") or {}
    if isinstance(meta, dict):
        for k in ("Timestamp", "timestamp", "SavedAt", "saved_at"):
            v = meta.get(k)
            if isinstance(v, str):
                candidates.append(v)
    for raw in candidates:
        raw2 = raw.replace("Z", "").strip()
        # try common formats then ISO
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                return dt.datetime.strptime(raw2[:19], fmt)
            except Exception:
                pass
        try:
            return dt.datetime.fromisoformat(raw2[:19])
        except Exception:
            pass
    return None

def canonical_ts_from_file(path: Path, use_mtime: bool) -> dt.datetime:
    try:
        with path.open("r", encoding="utf-8") as f:
            js = json.load(f)
        ts = parse_any_timestamp(js)
        if ts:
            return ts
    except Exception:
        pass
    if use_mtime:
        return dt.datetime.fromtimestamp(path.stat().st_mtime)
    # fallback: try filename fragments like "2025-09-20 14-33-00"
    name = path.stem
    for sep in ("_", " ", "."):
        parts = name.split(sep)
        for i in range(len(parts) - 1):
            chunk = parts[i] + " " + parts[i + 1].replace("-", ":")
            try:
                return dt.datetime.fromisoformat(chunk[:19])
            except Exception:
                continue
    return dt.datetime.fromtimestamp(path.stat().st_mtime)

# ---------------- Inventory helpers (ledger + initial) ----------------
def _norm_key(d: Dict[str, Any], *cands: str, default=None):
    for c in cands:
        if c in d: return d[c]
        cl = c.lower()
        cu = c.upper()
        if cl in d: return d[cl]
        if cu in d: return d[cu]
    return default

def _inventory_type(d: Dict[str, Any]) -> Optional[str]:
    t = _norm_key(d, "InventoryType", "Type", default=None)
    if isinstance(t, dict):
        t2 = _norm_key(t, "InventoryType")
        if isinstance(t2, str):
            return t2
        return None
    if isinstance(t, str):
        return t
    return None

def _is_item_slot(d: Dict[str, Any]) -> bool:
    # A slot counts if it has Id/ProductId/SubstanceId and an Amount
    if not isinstance(d, dict):
        return False
    if _norm_key(d, "Amount", "amount", "AMOUNT", "Qty", "Quantity", default=None) is None:
        return False
    rid = _norm_key(d, "Id", "ID", "id", "ProductId", "SubstanceId", default=None)
    return rid is not None

def _slot_records_from_inventory(inv: Dict[str, Any], want_types=("Product","Substance")) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    slots = (inv or {}).get("Slots", []) or []
    for s in slots:
        invt = _inventory_type(s) or ""
        if want_types and invt not in want_types:
            continue
        if not _is_item_slot(s):
            continue
        rid = _norm_key(s, "Id","ID","id","ProductId","SubstanceId")
        amt = _norm_key(s, "Amount","amount","AMOUNT","Qty","Quantity") or 0
        maxa = _norm_key(s, "MaxAmount","maxamount","MAXAMOUNT")
        pos = s.get("Index") or {}
        slot_x = _norm_key(pos, "X","x","col","Col","COL", default=0) or 0
        slot_y = _norm_key(pos, "Y","y","row","Row","ROW", default=0) or 0
        rows.append({
            "slot_x": int(slot_x),
            "slot_y": int(slot_y),
            "resource_id": str(rid),
            "resource_type": invt,
            "amount": int(amt),
            "max_amount": 0 if maxa is None else int(maxa),
        })
    return rows

def aggregate_inventory(js: Dict[str, Any], include_tech: bool=False) -> Dict[str, float]:
    want_types = ("Product","Substance") if not include_tech else ("Product","Substance","Technology")
    psd = (((js.get("BaseContext") or {}).get("PlayerStateData")) or {})
    owners = []

    # Player
    owners.append(psd.get("Inventory"))
    owners.append(psd.get("Inventory_Cargo"))

    # Ships
    for ship in psd.get("ShipOwnership") or []:
        owners.append(ship.get("Inventory"))
        owners.append(ship.get("Inventory_Cargo"))

    # Vehicles
    for veh in psd.get("VehicleOwnership") or []:
        owners.append(veh.get("Inventory"))
        owners.append(veh.get("Inventory_Cargo"))

    # Freighter
    if psd.get("FreighterInventory"):
        owners.append(psd.get("FreighterInventory"))
    if psd.get("FreighterInventory_Cargo"):
        owners.append(psd.get("FreighterInventory_Cargo"))

    # Storage containers known names
    for k in ("Chest1","Chest2","Chest3","Chest4","Chest5","Chest6","Chest7","Chest8","Chest9","Chest10",
              "ChestMagic","ChestMagic2"):
        if k in psd:
            owners.append(psd.get(k))

    totals: Dict[str, float] = {}
    for inv in owners:
        for r in _slot_records_from_inventory(inv or {}, want_types):
            key = r["resource_id"].upper()
            totals[key] = totals.get(key, 0.0) + float(r["amount"])
    return totals

def diff_inventories(prev: Dict[str, float], cur: Dict[str, float]) -> Dict[str, float]:
    keys = set(prev) | set(cur)
    return {k: cur.get(k, 0.0) - prev.get(k, 0.0) for k in keys}

def coalesce_sessions(snapshots: List[Dict[str, Any]], session_minutes: int) -> List[Dict[str, Any]]:
    if session_minutes <= 0 or len(snapshots) <= 1:
        return snapshots
    out: List[Dict[str, Any]] = []
    grp = [snapshots[0]]
    for s in snapshots[1:]:
        prev = grp[-1]
        delta_min = (s["ts"] - prev["ts"]).total_seconds() / 60.0
        if delta_min <= session_minutes:
            grp.append(s)
        else:
            out.append(grp[-1])
            grp = [s]
    if grp:
        out.append(grp[-1])
    return out

# ---------------- Initial import (CSV/SQL/DB) ----------------
def _escape_sql(val: str) -> str:
    return val.replace("\\", "\\\\").replace("'", "''")

def _collect_initial_rows(js: Dict[str, Any], save_path: Path, ts: dt.datetime, include_tech: bool, verbose: bool) -> List[Dict[str, Any]]:
    want_types = ("Product","Substance") if not include_tech else ("Product","Substance","Technology")
    psd = (((js.get("BaseContext") or {}).get("PlayerStateData")) or {})
    owners: List[Tuple[str, Optional[int], Optional[str], str, Dict[str, Any]]] = []

    # Player
    owners.append(("PLAYER", None, psd.get("Name") or None, "GENERAL", psd.get("Inventory")))
    owners.append(("PLAYER", None, psd.get("Name") or None, "CARGO",   psd.get("Inventory_Cargo")))

    # Ships
    for idx, ship in enumerate(psd.get("ShipOwnership") or []):
        owners.append(("SHIP", idx, ship.get("Name") or None, "GENERAL", ship.get("Inventory")))
        owners.append(("SHIP", idx, ship.get("Name") or None, "CARGO",   ship.get("Inventory_Cargo")))

    # Vehicles
    for idx, veh in enumerate(psd.get("VehicleOwnership") or []):
        owners.append(("VEHICLE", idx, veh.get("Name") or None, "GENERAL", veh.get("Inventory")))
        owners.append(("VEHICLE", idx, veh.get("Name") or None, "CARGO",   veh.get("Inventory_Cargo")))

    # Freighter
    if psd.get("FreighterInventory"):
        owners.append(("FREIGHTER", 0, psd.get("PlayerFreighterName") or None, "GENERAL", psd.get("FreighterInventory")))
    if psd.get("FreighterInventory_Cargo"):
        owners.append(("FREIGHTER", 0, psd.get("PlayerFreighterName") or None, "CARGO",   psd.get("FreighterInventory_Cargo")))

    # STORAGE containers
    storage_names = [
        ("Chest1", "STORAGE1"), ("Chest2", "STORAGE2"), ("Chest3", "STORAGE3"),
        ("Chest4", "STORAGE4"), ("Chest5", "STORAGE5"), ("Chest6", "STORAGE6"),
        ("Chest7", "STORAGE7"), ("Chest8", "STORAGE8"), ("Chest9", "STORAGE9"),
        ("Chest10", "STORAGE10"), ("ChestMagic", "STORAGEM"), ("ChestMagic2", "STORAGEM2"),
    ]
    for key, invname in storage_names:
        if psd.get(key):
            owners.append(("STORAGE", None, invname, "GENERAL", psd.get(key)))

    rows: List[Dict[str, Any]] = []
    for owner_type, owner_index, owner_name, inv_kind, inv in owners:
        for r in _slot_records_from_inventory(inv or {}, want_types):
            row = {
                "snapshot_ts": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "owner_type": owner_type,
                "owner_index": "" if owner_index is None else int(owner_index),
                "owner_name": owner_name or "",
                "inventory": inv_kind,
                **r,
                "source_file": str(save_path),
            }
            rows.append(row)
    if verbose:
        print(f"[INITIAL] collected owners: {len(owners)}, rows: {len(rows)}")
    return rows

def initial_import_to_csv_sql(save_path: Path, out_csv: Path, out_sql: Path, use_mtime=True, include_tech=False, verbose=False):
    with save_path.open("r", encoding="utf-8") as f:
        js = json.load(f)
    ts = canonical_ts_from_file(save_path, use_mtime)
    rows = _collect_initial_rows(js, save_path, ts, include_tech, verbose)

    # CSV
    fieldnames = ["snapshot_ts","owner_type","owner_index","owner_name","inventory",
                  "slot_x","slot_y","resource_id","resource_type","amount","max_amount","source_file"]
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames); w.writeheader(); w.writerows(rows)

    # SQL (MariaDB)
    ddl = """CREATE TABLE IF NOT EXISTS `nms_initial_items` (
  `snapshot_ts` DATETIME NOT NULL,
  `owner_type` ENUM('PLAYER','SHIP','VEHICLE','FREIGHTER','STORAGE') NOT NULL,
  `owner_index` INT NULL,
  `owner_name` VARCHAR(128) NOT NULL DEFAULT '',
  `inventory` ENUM('GENERAL','CARGO') NOT NULL,
  `slot_x` INT NOT NULL,
  `slot_y` INT NOT NULL,
  `resource_id` VARCHAR(64) NOT NULL,
  `resource_type` ENUM('Product','Substance','Technology') NOT NULL,
  `amount` INT NOT NULL,
  `max_amount` INT NOT NULL,
  `source_file` VARCHAR(255) NOT NULL,
  INDEX (`snapshot_ts`), INDEX (`owner_type`), INDEX (`inventory`),
  INDEX (`resource_id`), INDEX (`resource_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;"""
    with out_sql.open("w", encoding="utf-8") as f:
        f.write(ddl + "\n\nBEGIN;\n")
        for row in rows:
            vals = (
                row["snapshot_ts"],
                row["owner_type"],
                None if row["owner_index"]=="" else row["owner_index"],
                row["owner_name"],
                row["inventory"],
                row["slot_x"],
                row["slot_y"],
                row["resource_id"],
                row["resource_type"],
                row["amount"],
                row["max_amount"],
                row["source_file"],
            )
            def fmt(v):
                if v is None or v=="": return "NULL"
                if isinstance(v, (int,float)): return str(int(v))
                return "'" + _escape_sql(str(v)) + "'"
            f.write(
                "INSERT INTO `nms_initial_items` "
                "(`snapshot_ts`,`owner_type`,`owner_index`,`owner_name`,`inventory`,`slot_x`,`slot_y`,"
                "`resource_id`,`resource_type`,`amount`,`max_amount`,`source_file`) "
                f"VALUES ({','.join(fmt(v) for v in vals)});\n"
            )
        f.write("COMMIT;\n")

    if verbose:
        print(f"[INITIAL] rows: {len(rows)}")
        print(f"[INITIAL] CSV: {out_csv}")
        print(f"[INITIAL] SQL: {out_sql}")

# ---------------- DB helpers ----------------
def _load_env(env_path: Path) -> Dict[str, str]:
    env: Dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        if "=" not in line: continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    for k in ("DB_HOST","DB_USER","DB_PASS","DB_NAME"):
        if k not in env:
            raise RuntimeError(f"Missing {k} in {env_path}")
    if "DB_PORT" not in env: env["DB_PORT"] = "3306"
    return env

def _db_connect_from_env(env: Dict[str, str]):
    err = None
    try:
        import pymysql  # type: ignore
        conn = pymysql.connect(
            host=env["DB_HOST"], user=env["DB_USER"], password=env["DB_PASS"],
            database=env["DB_NAME"], port=int(env.get("DB_PORT","3306"))
        )
        return conn, "pymysql"
    except Exception as e:
        err = e
    try:
        import mysql.connector  # type: ignore
        conn = mysql.connector.connect(
            host=env["DB_HOST"], user=env["DB_USER"], password=env["DB_PASS"],
            database=env["DB_NAME"], port=int(env.get("DB_PORT","3306"))
        )
        return conn, "mysql.connector"
    except Exception as e2:
        err = (err, e2)
    raise RuntimeError(f"DB connection failed. Install PyMySQL or mysql-connector. Details: {err}")

def initial_import_to_db(save_path: Path, table: str, env_path: Path, use_mtime=True, include_tech=False, verbose=False):
    js = json.load(save_path.open("r", encoding="utf-8"))
    ts = canonical_ts_from_file(save_path, use_mtime)
    rows = _collect_initial_rows(js, save_path, ts, include_tech, verbose)
    env = _load_env(env_path)
    conn, backend = _db_connect_from_env(env)
    if verbose: print(f"[DB] Connected via {backend}")
    cur = conn.cursor()
    ddl = f"""
CREATE TABLE IF NOT EXISTS `{table}` (
  `snapshot_ts` DATETIME NOT NULL,
  `owner_type` ENUM('PLAYER','SHIP','VEHICLE','FREIGHTER','STORAGE') NOT NULL,
  `owner_index` INT NULL,
  `owner_name` VARCHAR(128) NOT NULL DEFAULT '',
  `inventory` ENUM('GENERAL','CARGO') NOT NULL,
  `slot_x` INT NOT NULL,
  `slot_y` INT NOT NULL,
  `resource_id` VARCHAR(64) NOT NULL,
  `resource_type` ENUM('Product','Substance','Technology') NOT NULL,
  `amount` INT NOT NULL,
  `max_amount` INT NOT NULL,
  `source_file` VARCHAR(255) NOT NULL,
  INDEX (`snapshot_ts`), INDEX (`owner_type`), INDEX (`inventory`),
  INDEX (`resource_id`), INDEX (`resource_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;""".strip()
    cur.execute(ddl)
    cols = ["snapshot_ts","owner_type","owner_index","owner_name","inventory","slot_x","slot_y",
            "resource_id","resource_type","amount","max_amount","source_file"]
    placeholders = ",".join(["%s"]*len(cols))
    sql = f"INSERT INTO `{table}` ({','.join('`'+c+'`' for c in cols)}) VALUES ({placeholders})"
    data = []
    for r in rows:
        data.append((
            r["snapshot_ts"],
            r["owner_type"],
            None if r["owner_index"]=="" else r["owner_index"],
            r["owner_name"],
            r["inventory"],
            r["slot_x"],
            r["slot_y"],
            r["resource_id"],
            r["resource_type"],
            r["amount"],
            r["max_amount"],
            r["source_file"],
        ))
    cur.executemany(sql, data)
    conn.commit()
    cur.close(); conn.close()
    if verbose: print(f"[DB] Inserted {len(rows)} rows into {table}")

# ---------------- NEW: Baseline from SQL/DB + helpers ----------------
def _split_sql_values_row(row: str) -> List[str]:
    """Split a single VALUES(...) row into tokens, handling single-quoted strings and commas."""
    vals: List[str] = []
    buf: List[str] = []
    in_str = False
    i, n = 0, len(row)
    while i < n:
        ch = row[i]
        if in_str:
            if ch == "'":
                if i + 1 < n and row[i+1] == "'":  # escaped ''
                    buf.append("'"); i += 2; continue
                in_str = False; i += 1; continue
            buf.append(ch); i += 1; continue
        else:
            if ch == "'":
                in_str = True; i += 1; continue
            if ch == ",":
                vals.append("".join(buf).strip()); buf = []; i += 1; continue
            buf.append(ch); i += 1; continue
    if buf or row.endswith(","):
        vals.append("".join(buf).strip())
    return vals

def parse_initial_sql_totals(sql_path: Path, include_tech: bool = False):
    """
    Parse an initial_items.sql dump and return (totals: {RESOURCE_ID: amount}, ts_min, ts_max).
    Assumes INSERT INTO `nms_initial_items` (...) VALUES (...);
    """
    text = sql_path.read_text(encoding="utf-8", errors="ignore")
    pattern = re.compile(
        r"INSERT\s+INTO\s+`?nms_initial_items`?.*?VALUES\s*\((.*?)\)\s*;",
        re.IGNORECASE | re.DOTALL,
    )
    totals: Dict[str, float] = {}
    ts_min = ts_max = None
    for m in pattern.finditer(text):
        row = m.group(1)
        vals = _split_sql_values_row(row)
        # expected at least: snapshot_ts .. resource_id, resource_type, amount ...
        if len(vals) < 12:
            continue
        snapshot_ts = vals[0].strip("'")
        resource_id = vals[7].strip("'")
        resource_type = vals[8].strip("'").upper()
        amount_str = vals[9].strip("'")
        try:
            amount = float(int(amount_str))
        except Exception:
            continue
        if not include_tech and resource_type == "TECHNOLOGY":
            continue
        key = resource_id.upper()
        totals[key] = totals.get(key, 0.0) + amount
        if snapshot_ts:
            if ts_min is None or snapshot_ts < ts_min: ts_min = snapshot_ts
            if ts_max is None or snapshot_ts > ts_max: ts_max = snapshot_ts
    return totals, ts_min, ts_max

def load_baseline_from_db(env_path: Path, table: str, snapshot: str = "latest", include_tech: bool = False):
    """
    Load baseline totals from MariaDB/MySQL table created by initial import.
    Returns (totals, target_ts_string).
    """
    env = _load_env(env_path)
    conn, backend = _db_connect_from_env(env)
    cur = conn.cursor()
    # choose snapshot_ts
    snap = snapshot.strip().lower()
    if snap in ("latest", "newest"):
        cur.execute(f"SELECT MAX(snapshot_ts) FROM `{table}`")
        row = cur.fetchone()
        target_ts = row[0]
    elif snap in ("oldest", "earliest"):
        cur.execute(f"SELECT MIN(snapshot_ts) FROM `{table}`")
        row = cur.fetchone()
        target_ts = row[0]
    else:
        target_ts = snapshot  # use as provided string

    if not target_ts:
        cur.close(); conn.close()
        raise RuntimeError("No snapshot_ts found in baseline table.")

    q = f"SELECT resource_id, resource_type, SUM(amount) FROM `{table}` WHERE snapshot_ts = %s"
    params = [target_ts]
    if not include_tech:
        q += " AND resource_type <> 'Technology'"
    q += " GROUP BY resource_id, resource_type"

    cur.execute(q, params)
    totals: Dict[str, float] = {}
    for rid, rtype, amt in cur.fetchall():
        rid_key = str(rid).upper()
        totals[rid_key] = totals.get(rid_key, 0.0) + float(amt or 0)
    cur.close(); conn.close()
    return totals, (str(target_ts) if not isinstance(target_ts, str) else target_ts)

def pick_latest_json_from_path(root: Path, use_mtime: bool, include_tech: bool=False):
    """
    If root is a file, return it; if directory, scan *.json and pick the latest by canonical_ts_from_file.
    Returns dict {ts, path, inv}.
    """
    candidates = []
    if root.is_file() and root.suffix.lower() == ".json":
        p = root
        ts = canonical_ts_from_file(p, use_mtime)
        js = json.load(p.open("r", encoding="utf-8"))
        inv = aggregate_inventory(js, include_tech=include_tech)
        candidates.append({"ts": ts, "path": p, "inv": inv})
    else:
        for p in sorted(root.rglob("*.json")):
            try:
                ts = canonical_ts_from_file(p, use_mtime)
                js = json.load(p.open("r", encoding="utf-8"))
                inv = aggregate_inventory(js, include_tech=include_tech)
                candidates.append({"ts": ts, "path": p, "inv": inv})
            except Exception:
                continue
    if not candidates:
        raise SystemExit("[ERR] --saves must point to a JSON or a folder containing JSON snapshots.")
    candidates.sort(key=lambda x: x["ts"])
    return candidates[-1]  # latest

# ---------------- Optional: write ledger to DB ----------------
def write_ledger_to_db(rows: List[Dict[str, str]], env_path: Path, table: str, verbose: bool=False):
    env = _load_env(env_path)
    conn, backend = _db_connect_from_env(env)
    cur = conn.cursor()
    ddl = f"""
CREATE TABLE IF NOT EXISTS `{table}` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `session_start` DATETIME NOT NULL,
  `session_end` DATETIME NOT NULL,
  `resource_id` VARCHAR(64) NOT NULL,
  `acquired` INT NOT NULL,
  `spent` INT NOT NULL,
  `net` INT NOT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  INDEX (`session_start`), INDEX (`session_end`), INDEX (`resource_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;""".strip()
    cur.execute(ddl)
    cols = ["session_start","session_end","resource_id","acquired","spent","net"]
    placeholders = ",".join(["%s"]*len(cols))
    sql = f"INSERT INTO `{table}` ({','.join('`'+c+'`' for c in cols)}) VALUES ({placeholders})"
    data = [(r["session_start"], r["session_end"], r["resource_id"],
             int(float(r["acquired"])), int(float(r["spent"])), int(float(r["net"])))
            for r in rows]
    if data:
        cur.executemany(sql, data)
    conn.commit()
    cur.close(); conn.close()
    if verbose:
        print(f"[DB] Ledger rows inserted: {len(rows)} into {table}")

# ---------------- Ledger runner ----------------
def run_ledger(args):
    # Baseline branch: compare single current JSON vs baseline (SQL or DB)
    if args.baseline_sql or args.baseline_db_table:
        cur_snap = pick_latest_json_from_path(Path(args.saves), args.use_mtime, include_tech=False)
        if args.verbose:
            print(f"[CUR] {cur_snap['path']} @ {cur_snap['ts'].isoformat()} with {len(cur_snap['inv'])} resources")

        if args.baseline_sql:
            base_totals, ts_min, ts_max = parse_initial_sql_totals(Path(args.baseline_sql), include_tech=args.baseline_include_tech)
            base_ts = ts_max or ts_min or "BASELINE"
            if args.verbose:
                print(f"[BASELINE:SQL] totals={len(base_totals)} from {args.baseline_sql} (snapshot_ts={base_ts})")
        else:
            if not args.db_env:
                raise SystemExit("[ERR] --baseline-db-table requires --db-env for DB credentials.")
            base_totals, base_ts = load_baseline_from_db(Path(args.db_env), args.baseline_db_table,
                                                         snapshot=args.baseline_snapshot,
                                                         include_tech=args.baseline_include_tech)
            if args.verbose:
                print(f"[BASELINE:DB] totals={len(base_totals)} from {args.baseline_db_table} (snapshot_ts={base_ts})")

        delta = diff_inventories(base_totals, cur_snap["inv"])
        ss = (base_ts if isinstance(base_ts, str) else str(base_ts))
        se = cur_snap["ts"].isoformat(timespec="seconds")

        ledger_rows: List[Dict[str, str]] = []
        totals: Dict[str, Dict[str, float]] = {}
        for rid, d in sorted(delta.items()):
            acq = max(d, 0.0); spent = max(-d, 0.0); net = d
            if acq == 0.0 and spent == 0.0:
                continue
            ledger_rows.append({
                "session_start": ss, "session_end": se, "resource_id": rid,
                "acquired": f"{acq:.0f}", "spent": f"{spent:.0f}", "net": f"{net:.0f}",
            })
            t = totals.setdefault(rid, {"acq":0.0, "spent":0.0})
            t["acq"] += acq; t["spent"] += spent

        with Path(args.out_ledger).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["session_start","session_end","resource_id","acquired","spent","net"])
            w.writeheader(); w.writerows(ledger_rows)

        with Path(args.out_totals).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["resource_id","lifetime_acquired","lifetime_spent","lifetime_net"])
            w.writeheader()
            for rid, t in sorted(totals.items()):
                w.writerow({"resource_id": rid,
                            "lifetime_acquired": f"{t['acq']:.0f}",
                            "lifetime_spent": f"{t['spent']:.0f}",
                            "lifetime_net": f"{(t['acq']-t['spent']):.0f}"})
        if args.db_write_ledger:
            if not args.db_env:
                raise SystemExit("[ERR] --db-write-ledger requires --db-env.")
            write_ledger_to_db(ledger_rows, Path(args.db_env), args.db_ledger_table, verbose=args.verbose)
        if args.verbose:
            print(f"[DONE] Baseline ledger -> {args.out_ledger}, {args.out_totals}")
        return

    # Multi-snapshot ledger (needs ≥2 JSONs)
    root = Path(args.saves)
    snapshots: List[Dict[str, Any]] = []
    if root.is_file() and root.suffix.lower()==".json":
        try:
            ts = canonical_ts_from_file(root, args.use_mtime)
            js = json.load(root.open("r", encoding="utf-8"))
            inv = aggregate_inventory(js, include_tech=False)
            snapshots.append({"ts": ts, "path": root, "inv": inv})
            if args.verbose: print(f"[OK] {root} -> {ts.isoformat()} ({len(inv)} resources)")
        except Exception as e:
            print(f"[WARN] Skipping {root}: {e}")
    else:
        for p in sorted(root.rglob("*.json")):
            try:
                ts = canonical_ts_from_file(p, args.use_mtime)
                js = json.load(p.open("r", encoding="utf-8"))
                inv = aggregate_inventory(js, include_tech=False)
                snapshots.append({"ts": ts, "path": p, "inv": inv})
                if args.verbose: print(f"[OK] {p} -> {ts.isoformat()} ({len(inv)} resources)")
            except Exception as e:
                print(f"[WARN] Skipping {p}: {e}")

    if len(snapshots) < 2:
        raise SystemExit("[ERR] Need at least 2 JSON snapshots to compute a ledger. Use --baseline-sql or --baseline-db-table when you only have one JSON.")

    snapshots.sort(key=lambda x: x["ts"])
    snapshots = coalesce_sessions(snapshots, args.session_minutes)

    ledger_rows: List[Dict[str, str]] = []
    totals: Dict[str, Dict[str, float]] = {}
    for i in range(1, len(snapshots)):
        prev, cur = snapshots[i-1], snapshots[i]
        delta = diff_inventories(prev["inv"], cur["inv"])
        ss = prev["ts"].isoformat(timespec="seconds")
        se = cur["ts"].isoformat(timespec="seconds")
        for rid, d in delta.items():
            acq = max(d, 0.0); spent = max(-d, 0.0); net = d
            if acq == 0.0 and spent == 0.0:
                continue
            ledger_rows.append({
                "session_start": ss, "session_end": se, "resource_id": rid,
                "acquired": f"{acq:.0f}", "spent": f"{spent:.0f}", "net": f"{net:.0f}",
            })
            t = totals.setdefault(rid, {"acq":0.0, "spent":0.0}); t["acq"] += acq; t["spent"] += spent

    with Path(args.out_ledger).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["session_start","session_end","resource_id","acquired","spent","net"])
        w.writeheader(); w.writerows(ledger_rows)

    with Path(args.out_totals).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["resource_id","lifetime_acquired","lifetime_spent","lifetime_net"])
        w.writeheader()
        for rid, t in sorted(totals.items()):
            w.writerow({"resource_id": rid,
                        "lifetime_acquired": f"{t['acq']:.0f}",
                        "lifetime_spent": f"{t['spent']:.0f}",
                        "lifetime_net": f"{(t['acq']-t['spent']):.0f}"})

    if args.db_write_ledger:
        if not args.db_env:
            raise SystemExit("[ERR] --db-write-ledger requires --db-env.")
        write_ledger_to_db(ledger_rows, Path(args.db_env), args.db_ledger_table, verbose=args.verbose)

    if args.verbose:
        print(f"[DONE] Ledger -> {args.out_ledger}")
        print(f"[DONE] Totals -> {args.out_totals}")

# ---------------- CLI ----------------
def main():
    ap = argparse.ArgumentParser(description="No Man's Sky: resource ledger and initial inventory export (v3).")
    ap.add_argument("--saves", required=True, help="Folder with exported JSON saves (or a single JSON path).")
    ap.add_argument("--use-mtime", action="store_true", help="Use file mtime if JSON lacks timestamp.")
    ap.add_argument("--verbose", action="store_true")

    # Ledger outputs
    ap.add_argument("--out-ledger", default="ledger.csv")
    ap.add_argument("--out-totals", default="totals.csv")
    ap.add_argument("--session-minutes", type=int, default=10, help="Coalesce snapshots <= N minutes apart (default: 10).")

    # Initial mode
    ap.add_argument("--initial", action="store_true", help="Initial export of Player/Ships/Vehicles/Freighter/Storage -> CSV and/or DB.")
    ap.add_argument("--out-initial-csv", default="initial_items.csv")
    ap.add_argument("--out-initial-sql", default="initial_items.sql")
    ap.add_argument("--include-tech", action="store_true", help="Include Technology slots (default off).")
    ap.add_argument("--db-import", action="store_true", help="Write rows directly into MariaDB/MySQL instead of a .sql file.")
    ap.add_argument("--db-env", default=None, help="Path to .env with DB creds (DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME).")
    ap.add_argument("--db-table", default="nms_initial_items", help="Destination table name when using --db-import.")

    # NEW: Baseline options
    ap.add_argument("--baseline-sql", help="Use an initial_items.sql file as baseline instead of an older JSON.")
    ap.add_argument("--baseline-db-table", help="Use a DB table from initial import as baseline (requires --db-env).")
    ap.add_argument("--baseline-snapshot", default="latest",
                    help="Which snapshot_ts to use (latest|oldest|YYYY-MM-DD[ HH:MM:SS]).")
    ap.add_argument("--baseline-include-tech", action="store_true",
                    help="Include Technology slots in the baseline totals.")

    # NEW: Write ledger to DB
    ap.add_argument("--db-write-ledger", action="store_true",
                    help="Insert computed ledger rows into MariaDB/MySQL.")
    ap.add_argument("--db-ledger-table", default="nms_ledger_deltas",
                    help="Destination table for ledger rows when --db-write-ledger is set.")

    args = ap.parse_args()

    if args.initial:
        path = Path(args.saves)
        if path.is_file():
            save_path = path
        else:
            # if folder, pick the latest *.json by timestamp
            latest = pick_latest_json_from_path(path, args.use_mtime)
            save_path = latest["path"]
            if args.verbose:
                print(f"[INITIAL] Using latest JSON in folder: {save_path}")

        if args.db_import:
            if not args.db_env:
                raise SystemExit("[ERR] --db-import requires --db-env pointing to a .env with DB creds.")
            initial_import_to_db(save_path, args.db_table, Path(args.db_env),
                                 use_mtime=args.use_mtime, include_tech=args.include_tech, verbose=args.verbose)
            print(f"[DONE] Initial import -> inserted into {args.db_table}")
        else:
            initial_import_to_csv_sql(save_path, Path(args.out_initial_csv), Path(args.out_initial_sql),
                                      use_mtime=args.use_mtime, include_tech=args.include_tech, verbose=args.verbose)
            print(f"[DONE] Initial import -> {args.out_initial_csv}, {args.out_initial_sql}")
        return

    run_ledger(args)

if __name__ == "__main__":
    main()
