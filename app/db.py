"""SQLite storage with field-level encryption at rest (Fernet / AES-128-CBC + HMAC).

Encrypted: customer names, phone numbers, notes, transcripts, reminder texts,
audit details. Plain: amounts (integer paise), dates, kinds, ids, so that every
dashboard figure is a SQL aggregate, never an LLM's guess.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from cryptography.fernet import Fernet

SCHEMA = """
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


class Crypto:
    def __init__(self, key: str | bytes):
        self._f = Fernet(key)

    def enc(self, value: str | None) -> bytes | None:
        if value is None:
            return None
        return self._f.encrypt(value.encode("utf-8"))

    def dec(self, blob: bytes | None) -> str | None:
        if blob is None:
            return None
        return self._f.decrypt(blob).decode("utf-8")


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
    """Single shared connection guarded by a lock. Kirana scale = tiny, fast queries."""

    def __init__(self, path: str, crypto: Crypto):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.crypto = crypto
        with self.lock:
            self.conn.executescript(SCHEMA)

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self.lock:
            return self.conn.execute(sql, params)

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        with self.lock:
            return self.conn.execute(sql, params).fetchone()

    def transaction(self):
        return _Tx(self)


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
