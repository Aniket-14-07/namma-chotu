"""Synthetic demo data. No real people, phone numbers are fictitious (98765 0xxxx)."""
from __future__ import annotations

from datetime import timedelta

from .ledger import Ledger
from .timeutil import today_ist

CUSTOMERS = [
    # name, devanagari (for natural TTS), phone, reminder opt-in
    ("Ramesh Kumar", "रमेश कुमार", "9876500001", True),
    ("Ramesh Sharma", "रमेश शर्मा", "9876500002", False),
    ("Suresh Yadav", "सुरेश यादव", "9876500003", True),
    ("Rahul Verma", "राहुल वर्मा", "9876500004", False),
    ("Priya Singh", "प्रिया सिंह", "9876500005", True),
    ("Amit Patel", "अमित पटेल", "9876500006", False),
    ("Sharma Ji", "शर्मा जी", "9876500007", False),
    ("Gupta Ji", "गुप्ता जी", "9876500008", True),
    ("Lakshmi Devi", "लक्ष्मी देवी", "9876500009", False),
    ("Mohammed Irfan", "मोहम्मद इरफ़ान", "9876500010", False),
    ("Anjali Nair", "अंजलि नायर", "9876500011", False),
    ("Kiran Gowda", "किरण गौड़ा", "9876500012", True),
]

# (customer index, kind, rupees, days ago)
HISTORY = [
    (0, "CREDIT", 900, 6), (0, "PAYMENT", 300, 4), (0, "CREDIT", 300, 1),
    (1, "CREDIT", 450, 3),
    (2, "CREDIT", 1200, 9), (2, "PAYMENT", 500, 2),
    (3, "CREDIT", 260, 1),
    (4, "CREDIT", 780, 5), (4, "PAYMENT", 780, 1),
    (5, "CREDIT", 1500, 12), (5, "CREDIT", 640, 3),
    (6, "CREDIT", 2100, 15), (6, "PAYMENT", 1000, 7),
    (7, "CREDIT", 350, 2),
    (8, "CREDIT", 520, 4),
    (9, "CREDIT", 1850, 8), (9, "PAYMENT", 850, 3),
    (10, "CREDIT", 95, 1),
    (11, "CREDIT", 3200, 20), (11, "PAYMENT", 1200, 10),
]


def seed(ledger: Ledger, with_history: bool = True) -> None:
    if ledger.customers:
        return
    created = [ledger.add_customer(n, name_hi=hi, phone=ph, reminder_opt_in=opt) for n, hi, ph, opt in CUSTOMERS]
    if not with_history:
        return
    t = today_ist()
    for idx, kind, rupees, ago in HISTORY:
        ledger.record(created[idx].id, kind, rupees * 100, t - timedelta(days=ago), source="seed")
