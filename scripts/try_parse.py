import sys
from datetime import datetime
from cryptography.fernet import Fernet
from app.db import Database, Crypto
from app.ledger import Ledger
from app.seed import seed
from app.timeutil import set_fixed_now, IST, today_ist
from app.nlu.parser import parse
set_fixed_now(datetime(2026,11,11,18,0,tzinfo=IST))
db=Database(":memory:", Crypto(Fernet.generate_key())); L=Ledger(db); seed(L)
for s in sys.argv[1:]:
    p=parse(s,L.customers,today_ist())
    print(f"\n>> {s}   [{p.lang_hint}] {p.tokens}")
    for c in p.clauses:
        m=c.mention; mn=None if not m else ([L.customer(i).name for i in m.candidates] if m.known else 'NEW:'+m.surface)
        nm=c.new_mention; nmn=None if not nm else ([L.customer(i).name for i in nm.candidates] if nm.known else 'NEW:'+nm.surface)
        print(f"   {c.intent:10} kind={c.kind}{'!' if c.kind_explicit else '?'} amt={c.amount and c.amount/100} who={mn} date={c.date} q={c.query} per={c.period_label} top={c.top_n} conf={c.confidence} new_amt={c.new_amount and c.new_amount/100} old={c.old_amount and c.old_amount/100} new_who={nmn} new_date={c.new_date} new_kind={c.new_kind} ord={c.ordinal}")
