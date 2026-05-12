# scripts/python/pipeline/ledger/cli_run.py
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple, Optional, Union
# Package-import shim for direct execution (python cli_run.py ...)
# Ensures repo root is on sys.path so absolute imports work even if __package__ is unset.
if __package__ in (None, ""):
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[5]))
from scripts.python.pipeline.ledger import (
    parse_any_timestamp, canonical_ts_from_file,
    aggregate_inventory, diff_inventories, coalesce_sessions, write_ledger_to_db,
    initial_import_to_csv_sql, parse_initial_sql_totals,
    _load_env, _manifest_source_mtime_safe, _db_connect_from_env,
    initial_import_to_db, load_baseline_from_db, pick_latest_json_from_path
)

def run_ledger(args) -> None:
    import re
    import sys
    from collections import defaultdict

    table = str(getattr(args, "db_ledger_table", "nms_ledger_deltas") or "nms_ledger_deltas")
    if not re.fullmatch(r"[A-Za-z0-9_]+", table):
        raise SystemExit(f"[ledger][ERROR] Unsafe ledger table name: {table!r}")

    if not bool(getattr(args, "db_write_ledger", False)):
        print("[ledger] --db-write-ledger not set; nothing written.", file=sys.stderr)
        return

    env_path = Path(getattr(args, "db_env", ".env"))
    conn = _db_connect_from_env(env_path)

    try:
        cur = conn.cursor()

        cur.execute("SHOW TABLES LIKE 'nms_snapshots'")
        if cur.fetchone() is None:
            raise SystemExit("[ledger][ERROR] Missing nms_snapshots table.")

        cur.execute("SHOW TABLES LIKE 'nms_items'")
        if cur.fetchone() is None:
            raise SystemExit("[ledger][ERROR] Missing nms_items table.")

        cur.execute(f"SHOW TABLES LIKE '{table}'")
        if cur.fetchone() is None:
            cur.execute(f"""
                CREATE TABLE `{table}` (
                  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                  from_snapshot_id BIGINT UNSIGNED NOT NULL,
                  to_snapshot_id BIGINT UNSIGNED NOT NULL,
                  resource_id VARCHAR(128) NOT NULL,
                  delta BIGINT NOT NULL,
                  computed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  PRIMARY KEY (id),
                  KEY idx_ledger_resource (resource_id),
                  KEY idx_ledger_pair (from_snapshot_id, to_snapshot_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            conn.commit()

        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        columns = {str(row[0]) for row in cur.fetchall()}
        required = {"from_snapshot_id", "to_snapshot_id", "resource_id", "delta"}
        missing = sorted(required - columns)
        if missing:
            raise SystemExit(
                "[ledger][ERROR] Unsupported nms_ledger_deltas schema; missing columns: "
                + ", ".join(missing)
            )

        cur.execute("""
            SELECT snapshot_id, save_root
              FROM nms_snapshots
             ORDER BY imported_at DESC, snapshot_id DESC
             LIMIT 1
        """)
        latest = cur.fetchone()
        if latest is None:
            print("[ledger] no snapshots found; nothing to compare.", file=sys.stderr)
            return

        latest_snapshot_id = int(latest[0])
        save_root = str(latest[1] or "")

        if save_root:
            cur.execute("""
                SELECT snapshot_id
                  FROM nms_snapshots
                 WHERE snapshot_id < %s
                   AND save_root = %s
                 ORDER BY imported_at DESC, snapshot_id DESC
                 LIMIT 1
            """, (latest_snapshot_id, save_root))
        else:
            cur.execute("""
                SELECT snapshot_id
                  FROM nms_snapshots
                 WHERE snapshot_id < %s
                 ORDER BY imported_at DESC, snapshot_id DESC
                 LIMIT 1
            """, (latest_snapshot_id,))

        previous = cur.fetchone()
        if previous is None:
            print(f"[ledger] snapshot {latest_snapshot_id} has no previous snapshot; nothing to compare.", file=sys.stderr)
            return

        previous_snapshot_id = int(previous[0])

        def load_totals(snapshot_id: int) -> Dict[str, int]:
            cur.execute("""
                SELECT resource_id, SUM(amount) AS amount
                  FROM nms_items
                 WHERE snapshot_id = %s
                 GROUP BY resource_id
            """, (snapshot_id,))
            totals: Dict[str, int] = {}
            for resource_id, amount in cur.fetchall():
                rid = str(resource_id or "").strip()
                if rid:
                    totals[rid] = int(amount or 0)
            return totals

        before = load_totals(previous_snapshot_id)
        after = load_totals(latest_snapshot_id)

        deltas: Dict[str, int] = {}
        for resource_id in sorted(set(before) | set(after)):
            delta = int(after.get(resource_id, 0)) - int(before.get(resource_id, 0))
            if delta != 0:
                deltas[resource_id] = delta

        cur.execute(
            f"DELETE FROM `{table}` WHERE from_snapshot_id = %s AND to_snapshot_id = %s",
            (previous_snapshot_id, latest_snapshot_id),
        )

        if deltas:
            insert_sql = (
                f"INSERT INTO `{table}` "
                "(from_snapshot_id, to_snapshot_id, resource_id, delta) "
                "VALUES (%s, %s, %s, %s)"
            )
            for resource_id, delta in deltas.items():
                cur.execute(insert_sql, (previous_snapshot_id, latest_snapshot_id, resource_id, delta))

        conn.commit()
        print(
            f"[ledger] wrote {len(deltas)} delta rows "
            f"from snapshot {previous_snapshot_id} to {latest_snapshot_id}.",
            file=sys.stderr,
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
