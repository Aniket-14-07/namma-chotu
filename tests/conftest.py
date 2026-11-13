import os
import sys
from datetime import datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import Crypto, Database  # noqa: E402
from app.dialogue import Session  # noqa: E402
from app.ledger import Ledger  # noqa: E402
from app.seed import seed  # noqa: E402
from app.timeutil import IST, set_fixed_now  # noqa: E402

NOW = datetime(2026, 11, 11, 18, 0, tzinfo=IST)   # a Wednesday


def fresh_db() -> Database:
    """In-memory SQLite, or a wiped Postgres when TEST_DATABASE_URL is set (same tests, both backends)."""
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        return Database(":memory:", Crypto(Fernet.generate_key()))
    import psycopg
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("DROP TABLE IF EXISTS reminders, transcripts, audit_log, transactions, customers CASCADE")
    return Database(url, Crypto(Fernet.generate_key()))


@pytest.fixture
def ledger():
    set_fixed_now(NOW)
    db = fresh_db()
    L = Ledger(db)
    seed(L)
    yield L
    set_fixed_now(None)


@pytest.fixture
def empty_ledger():
    set_fixed_now(NOW)
    db = fresh_db()
    L = Ledger(db)
    seed(L, with_history=False)
    yield L
    set_fixed_now(None)


@pytest.fixture
def session(empty_ledger):
    s = Session("test", empty_ledger)
    s.greeting()
    return s


def cid(ledger, name):
    return next(c.id for c in ledger.customers if c.name == name)
