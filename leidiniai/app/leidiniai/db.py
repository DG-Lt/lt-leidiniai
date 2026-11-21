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
        status        TEXT NOT NULL DEFAULT 'new', -- new|downloaded|parsed|parse_failed|waiting_parser|failed|expired|superseded
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
    # 2 – products, offers (prices in cents), watch list, category dictionary and shop category map
    """
    CREATE TABLE products (
        id              INTEGER PRIMARY KEY,
        chain           TEXT NOT NULL,
        ident           TEXT NOT NULL,          -- shop product id when stable (Lidl code, Rimi id), else name_key
        name            TEXT NOT NULL,          -- as printed (latest)
        name_key        TEXT NOT NULL,          -- plain-letter key (textutil.fold)
        quantity        TEXT,
        category        TEXT NOT NULL DEFAULT 'other',  -- English id (categories.CATEGORIES)
        category_source TEXT,                   -- user|shop|keyword|shop_weak|none
        category_locked INTEGER NOT NULL DEFAULT 0,      -- 1 = set by the user, never recomputed
        image           TEXT,                   -- latest image (local crop path under img/ or remote URL)
        first_seen      TEXT NOT NULL,
        last_seen       TEXT NOT NULL,
        UNIQUE (chain, ident)
    );
    CREATE INDEX products_key ON products (name_key);
    CREATE INDEX products_cat ON products (category);
    CREATE TABLE offers (
        id            INTEGER PRIMARY KEY,
        issue_id      INTEGER NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
        product_id    INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        chain         TEXT NOT NULL,
        seq           INTEGER NOT NULL,         -- order in the leaflet
        page          INTEGER,
        kind          TEXT NOT NULL,            -- price|badge|offer|hotspot
        name          TEXT NOT NULL,            -- as printed in this leaflet
        name_key      TEXT NOT NULL,
        price         INTEGER,                  -- cents
        old_price     INTEGER,
        discount_pct  INTEGER,
        discount_text TEXT,
        unit_price    INTEGER,
        unit          TEXT,
        quantity      TEXT,
        card          INTEGER NOT NULL DEFAULT 0,
        card_text     TEXT,
        valid_from    TEXT,                     -- offer dates, else the leaflet's
        valid_to      TEXT,
        category      TEXT NOT NULL DEFAULT 'other',
        ext_id        TEXT,
        ext_category  TEXT,
        image         TEXT,
        flags         TEXT NOT NULL DEFAULT '[]',
        extra         TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX offers_issue ON offers (issue_id);
    CREATE INDEX offers_product ON offers (product_id, valid_from);
    CREATE INDEX offers_valid ON offers (valid_to);
    CREATE TABLE watch (
        id        INTEGER PRIMARY KEY,
        term      TEXT NOT NULL,                -- as typed
        term_key  TEXT NOT NULL UNIQUE,         -- plain-letter key, matched as a substring of offers.name_key
        chain     TEXT,                         -- NULL = all chains
        created   TEXT NOT NULL,
        last_hit  TEXT
    );
    CREATE TABLE category_keywords (
        keyword_key TEXT PRIMARY KEY,           -- plain-letter stem or phrase
        category    TEXT NOT NULL,
        source      TEXT NOT NULL DEFAULT 'user',
        created     TEXT NOT NULL
    );
    CREATE TABLE category_map (
        chain        TEXT NOT NULL,
        ext_category TEXT NOT NULL,             -- Maxima section name, Rimi SH code (prefix)
        category     TEXT NOT NULL,
        strength     TEXT NOT NULL DEFAULT 'strong',  -- strong = decides alone, weak = after keywords
        PRIMARY KEY (chain, ext_category)
    );
    ALTER TABLE issues ADD COLUMN parse_attempts INTEGER NOT NULL DEFAULT 0;
    """,
    # 3 (0.4.1): IKI footer PDFs (policies, complaint rules) were taken for leaflets by 0.4.0 – drop them
    """
    DELETE FROM issues WHERE chain='iki' AND COALESCE(offers,0)=0
        AND (lower(key) LIKE '%privatumo%' OR lower(key) LIKE '%tvarka%' OR lower(key) LIKE '%taisykl%'
             OR lower(key) LIKE '%politika%' OR lower(key) LIKE '%salygos%');
    """,
    # 4 (0.4.7): offers stored before their leaflet's dates were known get the leaflet's dates
    """
    UPDATE offers SET
        valid_from = COALESCE(valid_from, (SELECT i.valid_from FROM issues i WHERE i.id = offers.issue_id)),
        valid_to   = COALESCE(valid_to,   (SELECT i.valid_to   FROM issues i WHERE i.id = offers.issue_id))
    WHERE valid_from IS NULL OR valid_to IS NULL;
    """,
    # 5 (0.5.2): Rimi leaflets filed as images-only before the viewer's PDF button was tried (0.4.6): download
    # them again, so the PDF button and the catalogue parser run (alcohol assortment catalogue Nr. 23)
    """
    UPDATE issues SET status='new', attempts=0, parse_attempts=0, error=NULL
    WHERE chain='rimi' AND status='waiting_parser' AND json_extract(meta, '$.parser') IS NULL
        AND (valid_to IS NULL OR valid_to >= date('now'));
    -- IKI leaflets still valid: parse the stored PDFs again with the name clean-up
    UPDATE issues SET status='downloaded', parse_attempts=0
    WHERE chain='iki' AND status='parsed' AND files LIKE '%.pdf%' AND (valid_to IS NULL OR valid_to >= date('now'));
    """,
    # 6 (0.8.0): picture reader results saved page by page (a restart continues from the next page); PDF leaflets
    # still valid are read again (short name + Aprašymas, size-only names, Lidl promotion terms)
    """
    CREATE TABLE IF NOT EXISTS vision_pages (
        issue_id INTEGER NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
        page     INTEGER NOT NULL,              -- 1-based page picture
        sig      TEXT NOT NULL,                 -- reader + model + prompt version + picture size: a change reads again
        offers   TEXT NOT NULL,                 -- JSON list of Offer.as_dict(), crop in pixels of the page picture
        seconds  REAL,
        read_at  TEXT NOT NULL,
        PRIMARY KEY (issue_id, page)
    );
    UPDATE issues SET status='downloaded', parse_attempts=0
    WHERE chain IN ('iki','lidl','norfa','rimi','vynoteka') AND status='parsed' AND files LIKE '%.pdf%'
        AND (valid_to IS NULL OR valid_to >= date('now'));
    """,
    # 7 (0.8.1): watch list "Tikslus žodis" per word (whole words only); all words in any order is the code's rule
    """
    ALTER TABLE watch ADD COLUMN exact INTEGER NOT NULL DEFAULT 0;
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
            try:
                conn.executescript(sql)
            except sqlite3.OperationalError as e:
                # a single ADD COLUMN migration run again on a database that already has the column
                if "duplicate column name" not in str(e) or sql.count(";") != 1:
                    raise
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
