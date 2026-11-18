"""SQLite storage. Schema changes are numbered migrations (PRAGMA user_version)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS: list[str] = [
    # 1 – leaflets (issues), per-chain check state, runs, key/value state
    """
    CREATE TABLE issues (
        id            INTEGER PRIMARY KEY,
        chain         TEXT NOT NULL,
        key           TEXT NOT NULL,            -- unique per chain, e.g. IKI file name, Lidl slug
        series        TEXT NOT NULL,            -- leaflet line, e.g. 'bazinis', 'weekly', 'maisto-prekiu-pasiulymai'
        title         TEXT NOT NULL,            -- as printed by the shop
        number        TEXT,                     -- issue number as printed ('47', '23 (523)')
        valid_from    TEXT,                     -- ISO date or NULL
        valid_to      TEXT,
        source_url    TEXT,
        files         TEXT NOT NULL DEFAULT '[]',  -- JSON [{url, name, path, sha256, bytes}]
        meta          TEXT NOT NULL DEFAULT '{}',  -- JSON, chain specific
        status        TEXT NOT NULL DEFAULT 'new', -- new|downloaded|parsed|waiting_parser|failed|expired|superseded
        attempts      INTEGER NOT NULL DEFAULT 0,
        offers        INTEGER,
        error         TEXT,
        first_seen    TEXT NOT NULL,
        last_seen     TEXT NOT NULL,
        downloaded_at TEXT,
        parsed_at     TEXT,
        UNIQUE (chain, key)
    );
    CREATE INDEX issues_chain_valid ON issues (chain, valid_to);
    CREATE TABLE chain_state (
        chain       TEXT PRIMARY KEY,
        last_check  TEXT,
        last_ok     TEXT,
        last_error  TEXT,
        last_run_id INTEGER
    );
    CREATE TABLE runs (
        id        INTEGER PRIMARY KEY,
        chain     TEXT NOT NULL,
        trigger   TEXT NOT NULL,                -- night|manual|startup|mqtt
        started   TEXT NOT NULL,
        finished  TEXT,
        status    TEXT NOT NULL DEFAULT 'running', -- running|ok|warning|error
        summary   TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX runs_chain ON runs (chain, started);
    CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT);
    """,
]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    for i, sql in enumerate(MIGRATIONS[v:], start=v + 1):
        with conn:
            conn.executescript(sql)
            conn.execute(f"PRAGMA user_version={i}")
    return conn.execute("PRAGMA user_version").fetchone()[0]


def open_db(settings) -> sqlite3.Connection:
    conn = connect(settings.db_path)
    migrate(conn)
    return conn


@contextmanager
def session(settings):
    conn = open_db(settings)
    try:
        yield conn
    finally:
        conn.close()


def kv_get(conn, key, default=None):
    r = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(r[0]) if r else default


def kv_set(conn, key, value) -> None:
    with conn:
        conn.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (key, json.dumps(value, ensure_ascii=False)))


def row_json(row, col):
    v = row[col]
    return json.loads(v) if v else None
