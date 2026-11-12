"""Text REPL / scripted run against the real dialogue engine (no audio). Usage:
   python scripts/chat.py "utt1" "utt2" ...     or   python scripts/chat.py   (interactive)"""
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cryptography.fernet import Fernet
from app.db import Database, Crypto
from app.ledger import Ledger
from app.seed import seed
from app.dialogue import Session
from app.timeutil import set_fixed_now, IST

set_fixed_now(datetime(2026, 11, 11, 18, 0, tzinfo=IST))
db = Database(":memory:", Crypto(Fernet.generate_key())); L = Ledger(db); seed(L)
s = Session("cli", L)
print("AGENT:", s.greeting().display)
utts = sys.argv[1:] or iter(lambda: input("YOU: "), "q")
for u in utts:
    r = s.handle(u)
    if r is None:
        print("   (ignored)"); continue
    if sys.argv[1:]: print(f"\nYOU:   {u}")
    print(f"AGENT: {r.display}   [{r.lang} {r.intents} {r.nlu_ms}ms]{'  PENDING:'+r.pending['kind'] if r.pending else ''}")
    for e in r.events:
        if e['type']=='txn': t=e['txn']; print(f"   - {e['action']:9} #{t['id']} {t['customer']:15} {t['kind']:7} {t['amount_paise']/100:>8} {t['txn_date']}")
        else: print("   -", e)
