"""Storage: SQLite locally, Postgres when DATABASE_URL is set (hosted, survives restarts).
Field-level encryption at rest (Fernet / AES-128-CBC + HMAC).

Encrypted: customer names, phone numbers, notes, transcripts, reminder texts,
audit details. Plain: amounts (integer paise), dates, kinds, ids, so that every
dashboard figure is a SQL aggregate, never an LLM's guess.
"""
from __future__ import annotations

import base64
import hashlib
import re
import sqlite3
import threading
from pathlib import Path

from cryptography.fernet import Fernet

SCHEMA = """
CREATE TABLE IF NOT EXISTS alarms (
    id          INTEGER PRIMARY KEY,
    due_at      TEXT NOT NULL,              -- ISO-8601 IST
    text_enc    BLOB NOT NULL,
    customer_id INTEGER REFERENCES customers(id),
    status      TEXT NOT NULL DEFAULT 'pending',   -- pending | done | cancelled
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT);

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS customers (
    id              INTEGER PRIMARY KEY,
    name_enc        BLOB NOT NULL,
    name_hi_enc     BLOB,
    phone_enc       BLOB,
    reminder_opt_in INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS transactions (
    id            INTEGER PRIMARY KEY,
    customer_id   INTEGER NOT NULL REFERENCES customers(id),
    kind          TEXT NOT NULL CHECK (kind IN ('CREDIT','PAYMENT')),
    amount_paise  INTEGER NOT NULL CHECK (amount_paise > 0),
    txn_date      TEXT NOT NULL,           -- YYYY-MM-DD, IST
    created_at    TEXT NOT NULL,           -- ISO-8601 with +05:30
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','voided')),
    void_reason   TEXT,
    replaced_by   INTEGER REFERENCES transactions(id),
    replaces      INTEGER REFERENCES transactions(id),
    source        TEXT NOT NULL DEFAULT 'voice',
    session_id    TEXT,
    utterance_id  TEXT,
    confidence    REAL,
    note_enc      BLOB
);
CREATE INDEX IF NOT EXISTS ix_txn_customer ON transactions(customer_id, status);
CREATE INDEX IF NOT EXISTS ix_txn_date ON transactions(txn_date, status);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY,
    ts          TEXT NOT NULL,
    action      TEXT NOT NULL,
    txn_id      INTEGER,
    customer_id INTEGER,
    session_id  TEXT,
    details_enc BLOB
);

CREATE TABLE IF NOT EXISTS transcripts (
    id         INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    ts         TEXT NOT NULL,
    role       TEXT NOT NULL,
    lang       TEXT,
    text_enc   BLOB NOT NULL,
    latency_ms INTEGER
);

CREATE TABLE IF NOT EXISTS reminders (
    id          INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    created_at  TEXT NOT NULL,
    message_enc BLOB NOT NULL,
    status      TEXT NOT NULL DEFAULT 'draft'
);
"""



PG_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT)""",
    """CREATE TABLE IF NOT EXISTS customers (
        id BIGSERIAL PRIMARY KEY, name_enc BYTEA NOT NULL, name_hi_enc BYTEA, phone_enc BYTEA,
        reminder_opt_in INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)""",
    """CREATE TABLE IF NOT EXISTS transactions (
        id BIGSERIAL PRIMARY KEY, customer_id BIGINT NOT NULL REFERENCES customers(id),
        kind TEXT NOT NULL CHECK (kind IN ('CREDIT','PAYMENT')),
        amount_paise BIGINT NOT NULL CHECK (amount_paise > 0), txn_date TEXT NOT NULL, created_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','voided')), void_reason TEXT,
        replaced_by BIGINT REFERENCES transactions(id), replaces BIGINT REFERENCES transactions(id),
        source TEXT NOT NULL DEFAULT 'voice', session_id TEXT, utterance_id TEXT, confidence REAL, note_enc BYTEA)""",
    "CREATE INDEX IF NOT EXISTS ix_txn_customer ON transactions(customer_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_txn_date ON transactions(txn_date, status)",
    """CREATE TABLE IF NOT EXISTS audit_log (
        id BIGSERIAL PRIMARY KEY, ts TEXT NOT NULL, action TEXT NOT NULL, txn_id BIGINT, customer_id BIGINT,
        session_id TEXT, details_enc BYTEA)""",
    """CREATE TABLE IF NOT EXISTS transcripts (
        id BIGSERIAL PRIMARY KEY, session_id TEXT NOT NULL, ts TEXT NOT NULL, role TEXT NOT NULL, lang TEXT,
        text_enc BYTEA NOT NULL, latency_ms INTEGER)""",
    """CREATE TABLE IF NOT EXISTS alarms (
        id BIGSERIAL PRIMARY KEY, due_at TEXT NOT NULL, text_enc BYTEA NOT NULL, customer_id BIGINT REFERENCES customers(id),
        status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL)""",
    "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS txn_time TEXT",
    """CREATE TABLE IF NOT EXISTS reminders (
        id BIGSERIAL PRIMARY KEY, customer_id BIGINT NOT NULL REFERENCES customers(id), created_at TEXT NOT NULL,
        message_enc BYTEA NOT NULL, status TEXT NOT NULL DEFAULT 'draft')""",
]


def fernet_key(secret: str | bytes) -> bytes:
    """Accept a real Fernet key, or derive one from any secret string (e.g. a host-generated value)."""
    raw = secret.encode() if isinstance(secret, str) else secret
    try:
        Fernet(raw)
        return raw
    except Exception:
        return base64.urlsafe_b64encode(hashlib.sha256(raw).digest())


class Crypto:
    def __init__(self, key: str | bytes):
        self._f = Fernet(fernet_key(key))

    def enc(self, value: str | None) -> bytes | None:
        if value is None:
            return None
        return self._f.encrypt(value.encode("utf-8"))

    def dec(self, blob: bytes | None) -> str | None:
        if blob is None:
            return None
        return self._f.decrypt(bytes(blob)).decode("utf-8")


def load_or_create_key(explicit: str, key_file: Path) -> str:
    """Use LEDGER_KEY if set, else a local key file (created once, never committed)."""
    if explicit:
        return explicit
    if key_file.exists():
        return key_file.read_text().strip()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key().decode()
    key_file.write_text(key)
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    return key


class Database:
    """Single shared connection guarded by a lock. Kirana scale = tiny, fast queries.
    path = SQLite file path, ":memory:", or a postgres:// URL."""

    def __init__(self, path: str, crypto: Crypto):
        self.crypto = crypto
        self.lock = threading.RLock()
        self.is_pg = path.startswith(("postgres://", "postgresql://"))
        if self.is_pg:
            self.conn = _PgConn(path)
            for stmt in PG_SCHEMA:
                self.conn.execute(stmt)
            return
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.executescript(SCHEMA)
            cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(transactions)")}
            if "txn_time" not in cols:          # added Nov 2026: time of day of an entry (HH:MM, IST)
                self.conn.execute("ALTER TABLE transactions ADD COLUMN txn_time TEXT")

    def execute(self, sql: str, params: tuple | dict = ()):
        with self.lock:
            return self.conn.execute(sql, params)

    def query(self, sql: str, params: tuple | dict = ()) -> list:
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple | dict = ()):
        with self.lock:
            return self.conn.execute(sql, params).fetchone()

    def transaction(self):
        return _Tx(self)


_INSERT = re.compile(r"^\s*INSERT\s", re.I)


class _PgCursor:
    def __init__(self, cur, lastrowid=None):
        self._cur = cur
        self.lastrowid = lastrowid
        self.rowcount = cur.rowcount

    def fetchall(self):
        return self._cur.fetchall() if self._cur.description else []

    def fetchone(self):
        return self._cur.fetchone() if self._cur.description else None


class _PgConn:
    """Makes psycopg look like the sqlite3 connection the ledger already uses:
    '?' placeholders, cur.lastrowid on INSERT, BEGIN IMMEDIATE, dict-like rows.
    Reconnects once if the hosted database dropped an idle connection."""

    def __init__(self, url: str):
        import psycopg  # only needed when DATABASE_URL is set
        from psycopg.rows import dict_row
        self._psycopg, self._dict_row, self.url = psycopg, dict_row, url
        self._in_tx = False
        self._connect()

    def _connect(self):
        self._c = self._psycopg.connect(self.url, autocommit=True, row_factory=self._dict_row)

    def execute(self, sql: str, params=()):
        s = sql.strip()
        if s.upper().startswith("BEGIN"):
            s = "BEGIN"
        s = s.replace("?", "%s")
        returning = bool(_INSERT.match(s)) and "RETURNING" not in s.upper() and "INTO APP_SETTINGS" not in s.upper()
        if returning:
            s += " RETURNING id"
        try:
            cur = self._c.execute(s, params)
        except self._psycopg.OperationalError:
            if self._in_tx or s == "COMMIT":
                raise
            self._connect()
            cur = self._c.execute(s, params)
        if s == "BEGIN":
            self._in_tx = True
        elif s in ("COMMIT", "ROLLBACK"):
            self._in_tx = False
        rid = cur.fetchone()["id"] if returning else None
        return _PgCursor(cur, rid)


class _Tx:
    def __init__(self, db: Database):
        self.db = db

    def __enter__(self):
        self.db.lock.acquire()
        self.db.conn.execute("BEGIN IMMEDIATE")
        return self.db

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.db.conn.execute("COMMIT")
            else:
                self.db.conn.execute("ROLLBACK")
        finally:
            self.db.lock.release()
        return False
