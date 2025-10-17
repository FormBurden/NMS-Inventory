# scripts/python/pipeline/ledger/db_conn.py
from typing import Any, Dict, Optional
from pathlib import Path
import os
import json

def _load_env(env_path: Path) -> Dict[str, str]:
    env: Dict[str,str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if "=" in line:
            k,v = line.split("=",1)
            env[k.strip()] = v.strip().strip('"')
    return env

def _manifest_source_mtime_safe(manifest_path: Path) -> Optional[int]:
    try:
        return int(manifest_path.stat().st_mtime)
    except Exception:
        return None

def _db_connect_from_env(env_path: Path):
    env = _load_env(env_path)
    import mariadb
    conn = mariadb.connect(
        host=env.get("DB_HOST","127.0.0.1"),
        user=env.get("DB_USER","nms_user"),
        password=env.get("DB_PASSWORD",""),
        database=env.get("DB_NAME","nms_database"),
        autocommit=False,
    )
    return conn
