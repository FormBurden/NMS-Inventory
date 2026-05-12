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

    def first_value(*names: str, default: str = "") -> str:
        for name in names:
            value = env.get(name) or os.environ.get(name)
            if value is not None and str(value).strip() != "":
                return str(value).strip()
        return default

    port_raw = first_value("DB_PORT", "NMS_DB_PORT", default="3306")
    try:
        port = int(port_raw)
    except ValueError:
        port = 3306

    host = first_value("DB_HOST", "NMS_DB_HOST", default="127.0.0.1")
    user = first_value("DB_USER", "NMS_DB_USER", default="nms_user")
    password = first_value("DB_PASSWORD", "DB_PASS", "NMS_DB_PASS", "MYSQL_PWD", default="")
    database = first_value("DB_NAME", "NMS_DB_NAME", "NMS_DB_DATABASE", default="nms_database")

    try:
        import mariadb
        return mariadb.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            autocommit=False,
        )
    except ModuleNotFoundError:
        return _MariaCliConnection(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
        )


class _MariaCliConnection:
    def __init__(self, *, host: str, port: int, user: str, password: str, database: str):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database

    def cursor(self):
        return _MariaCliCursor(self)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


class _MariaCliCursor:
    def __init__(self, conn: _MariaCliConnection):
        self.conn = conn
        self._rows = []

    def execute(self, sql: str, params=None) -> None:
        import subprocess

        rendered_sql = _render_sql(sql, params)
        argv = [
            "mariadb",
            "-h", self.conn.host,
            "-P", str(self.conn.port),
            "-u", self.conn.user,
        ]

        if self.conn.password:
            argv.append(f"-p{self.conn.password}")
        else:
            argv.append("-p")

        argv.extend([
            "-D", self.conn.database,
            "-N",
            "-B",
            "-e", rendered_sql,
        ])

        result = subprocess.run(
            argv,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"mariadb exited with {result.returncode}")

        self._rows = _parse_tsv_rows(result.stdout)

    def fetchone(self):
        if not self._rows:
            return None
        return self._rows.pop(0)

    def fetchall(self):
        rows = self._rows
        self._rows = []
        return rows


def _render_sql(sql: str, params=None) -> str:
    if not params:
        return sql

    parts = sql.split("%s")
    if len(parts) - 1 != len(params):
        raise ValueError("SQL placeholder count does not match parameter count")

    out = [parts[0]]
    for value, tail in zip(params, parts[1:]):
        out.append(_sql_literal(value))
        out.append(tail)
    return "".join(out)


def _sql_literal(value) -> str:
    if value is None:
        return "NULL"

    if isinstance(value, bool):
        return "1" if value else "0"

    if isinstance(value, int):
        return str(value)

    text = str(value)
    text = text.replace("\\", "\\\\").replace("'", "''")
    return f"'{text}'"


def _parse_tsv_rows(stdout: str):
    rows = []
    for line in stdout.splitlines():
        if not line:
            continue
        rows.append(tuple(_parse_tsv_value(part) for part in line.split("\t")))
    return rows


def _parse_tsv_value(value: str):
    if value == "NULL":
        return None

    try:
        return int(value)
    except ValueError:
        return value
