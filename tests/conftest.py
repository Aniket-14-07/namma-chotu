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


@pytest.fixture
def ledger():
    set_fixed_now(NOW)
    db = Database(":memory:", Crypto(Fernet.generate_key()))
    L = Ledger(db)
    seed(L)
    yield L
    set_fixed_now(None)


@pytest.fixture
def empty_ledger():
    set_fixed_now(NOW)
    db = Database(":memory:", Crypto(Fernet.generate_key()))
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
