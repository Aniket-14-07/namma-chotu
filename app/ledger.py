"""Deterministic ledger engine. The only code allowed to change balances.

Rules
- Money is integer paise. CREDIT raises what a customer owes; PAYMENT lowers it.
- Corrections never edit rows: the old row is voided and a new row `replaces` it,
  so the audit trail shows exactly what was said and what was fixed.
- Balance = SUM(active credits) - SUM(active payments). Negative = advance, and
  the dialogue layer only allows that after an explicit spoken confirmation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .db import Database
from .nlu.romanize import pkey, romanize
from .timeutil import now_ist, today_ist


@dataclass
class Customer:
    id: int
    name: str
    name_hi: str | None
    phone: str | None
    reminder_opt_in: bool
    keys: dict[str, str]   # alias key -> alias kind ("full","first","last","hi")

    @property
    def first(self) -> str:
        return self.name.split()[0]


@dataclass
class Txn:
    id: int
    customer_id: int
    kind: str
    amount_paise: int
    txn_date: str
    created_at: str
    status: str
    replaces: int | None = None
    txn_time: str | None = None      # "HH:MM" IST, when known


def _aliases(name: str, name_hi: str | None) -> dict[str, str]:
    parts = [p for p in name.lower().replace(".", " ").split() if p]
    out: dict[str, str] = {}
    if parts:
        out[pkey("".join(parts))] = "full"
        if len(parts) > 1:
            if parts[-1] != "ji":
                out.setdefault(pkey(parts[-1]), "last")
                out.setdefault(pkey(parts[-1] + "ji"), "last")
            out.setdefault(pkey(parts[0]), "first")
            if parts[-1] == "ji":
                out.setdefault(pkey(parts[0]), "full")
        else:
            out.setdefault(pkey(parts[0] + "ji"), "full")
    if name_hi:
        out.setdefault(pkey(romanize(name_hi).replace(" ", "")), "full")
    return out


class Ledger:
    def __init__(self, db: Database):
        self.db = db
        self._customers: dict[int, Customer] = {}
        self.reload_customers()

    # ---------------------------------------------------------------- customers
    def reload_customers(self) -> None:
        rows = self.db.query("SELECT * FROM customers WHERE active=1")
        c = self.db.crypto
        self._customers = {}
        for r in rows:
            name = c.dec(r["name_enc"]) or ""
            name_hi = c.dec(r["name_hi_enc"])
            self._customers[r["id"]] = Customer(
                id=r["id"], name=name, name_hi=name_hi, phone=c.dec(r["phone_enc"]),
                reminder_opt_in=bool(r["reminder_opt_in"]), keys=_aliases(name, name_hi),
            )

    @property
    def customers(self) -> list[Customer]:
        return list(self._customers.values())

    def customer(self, cid: int) -> Customer:
        return self._customers[cid]

    def add_customer(self, name: str, name_hi: str | None = None, phone: str | None = None,
                     reminder_opt_in: bool = False, session_id: str | None = None) -> Customer:
        name = self.clean_name(name)
        c = self.db.crypto
        with self.db.transaction() as db:
            cur = db.conn.execute(
                "INSERT INTO customers(name_enc,name_hi_enc,phone_enc,reminder_opt_in,created_at) VALUES(?,?,?,?,?)",
                (c.enc(name), c.enc(name_hi), c.enc(phone), int(reminder_opt_in), now_ist().isoformat()),
            )
            cid = cur.lastrowid
            self._audit(db, "CUSTOMER_CREATED", None, cid, session_id, {"name": name})
        self.reload_customers()
        return self._customers[cid]

    @staticmethod
    def clean_name(name: str) -> str:
        return " ".join(w.capitalize() if w.islower() else w for w in name.strip().split())

    def find_by_name(self, name: str) -> Customer | None:
        """Exact (case/space-insensitive) match on the full name, for duplicate checks."""
        key = "".join(name.lower().split())
        for c in self._customers.values():
            if "".join(c.name.lower().split()) == key:
                return c
        return None

    def update_customer(self, cid: int, *, name: str | None = None, name_hi: str | None = None,
                        phone: str | None = None, clear_name_hi: bool = False,
                        session_id: str | None = None) -> Customer:
        if cid not in self._customers:
            raise KeyError(cid)
        old = self._customers[cid]
        c = self.db.crypto
        sets, params, details = [], [], {}
        if name and self.clean_name(name) != old.name:
            new = self.clean_name(name)
            sets.append("name_enc=?"); params.append(c.enc(new)); details.update({"from": old.name, "to": new})
            if not name_hi:
                clear_name_hi = True        # old Devanagari spelling no longer matches
        if name_hi:
            sets.append("name_hi_enc=?"); params.append(c.enc(name_hi))
        elif clear_name_hi:
            sets.append("name_hi_enc=?"); params.append(None)
        if phone is not None:
            sets.append("phone_enc=?"); params.append(c.enc(phone or None))
        if sets:
            with self.db.transaction() as db:
                db.conn.execute(f"UPDATE customers SET {', '.join(sets)} WHERE id=?", (*params, cid))
                self._audit(db, "CUSTOMER_UPDATED", None, cid, session_id, details)
            self.reload_customers()
        return self._customers[cid]

    def remove_customer(self, cid: int, session_id: str | None = None) -> None:
        """Soft delete (hidden, history kept). Only allowed when nothing is due either way."""
        if self.balance(cid) != 0:
            raise ValueError("balance not zero")
        with self.db.transaction() as db:
            db.conn.execute("UPDATE customers SET active=0 WHERE id=?", (cid,))
            self._audit(db, "CUSTOMER_REMOVED", None, cid, session_id, {})
        self.reload_customers()

    def set_opt_in(self, cid: int, opt_in: bool) -> None:
        with self.db.transaction() as db:
            db.conn.execute("UPDATE customers SET reminder_opt_in=? WHERE id=?", (int(opt_in), cid))
            self._audit(db, "REMINDER_OPT_IN" if opt_in else "REMINDER_OPT_OUT", None, cid, None, {})
        self.reload_customers()

    # ------------------------------------------------------------- transactions
    def record(self, customer_id: int, kind: str, amount_paise: int, txn_date: date | None = None, *,
               session_id: str | None = None, utterance_id: str | None = None,
               confidence: float | None = None, note: str | None = None, source: str = "voice",
               replaces: int | None = None, txn_time: str | None = None) -> Txn:
        if kind not in ("CREDIT", "PAYMENT"):
            raise ValueError(f"bad kind {kind}")
        if amount_paise <= 0:
            raise ValueError("amount must be positive")
        if customer_id not in self._customers:
            raise KeyError(customer_id)
        d = (txn_date or today_ist()).isoformat()
        now = now_ist()
        created = now.isoformat()
        if txn_time is None and d == now.date().isoformat():
            txn_time = now.strftime("%H:%M")          # said today without a time -> stamp it now
        with self.db.transaction() as db:
            cur = db.conn.execute(
                "INSERT INTO transactions(customer_id,kind,amount_paise,txn_date,created_at,source,session_id,"
                "utterance_id,confidence,note_enc,replaces,txn_time) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (customer_id, kind, amount_paise, d, created, source, session_id, utterance_id, confidence,
                 db.crypto.enc(note), replaces, txn_time),
            )
            tid = cur.lastrowid
            if replaces:
                db.conn.execute(
                    "UPDATE transactions SET status='voided', void_reason='corrected', replaced_by=? WHERE id=?",
                    (tid, replaces))
            self._audit(db, "TXN_CORRECTED" if replaces else "TXN_CREATED", tid, customer_id, session_id,
                        {"kind": kind, "paise": amount_paise, "date": d, "replaces": replaces})
        return self.txn(tid)

    def correct(self, txn_id: int, *, customer_id: int | None = None, kind: str | None = None,
                amount_paise: int | None = None, txn_date: date | None = None,
                session_id: str | None = None) -> Txn:
        old = self.txn(txn_id)
        if old.status != "active":
            raise ValueError("transaction already voided")
        return self.record(
            customer_id or old.customer_id, kind or old.kind, amount_paise or old.amount_paise,
            txn_date or date.fromisoformat(old.txn_date), session_id=session_id, replaces=txn_id,
            source="voice-correction", txn_time=old.txn_time if not txn_date else None,
        )

    def void(self, txn_id: int, reason: str = "undo", session_id: str | None = None) -> Txn:
        old = self.txn(txn_id)
        if old.status != "active":
            raise ValueError("transaction already voided")
        with self.db.transaction() as db:
            db.conn.execute("UPDATE transactions SET status='voided', void_reason=? WHERE id=?", (reason, txn_id))
            self._audit(db, "TXN_VOIDED", txn_id, old.customer_id, session_id, {"reason": reason})
        return self.txn(txn_id)

    def txn(self, tid: int) -> Txn:
        r = self.db.one("SELECT * FROM transactions WHERE id=?", (tid,))
        if r is None:
            raise KeyError(tid)
        return Txn(id=r["id"], customer_id=r["customer_id"], kind=r["kind"], amount_paise=r["amount_paise"],
                   txn_date=r["txn_date"], created_at=r["created_at"], status=r["status"], replaces=r["replaces"],
                   txn_time=r["txn_time"])

    # ------------------------------------------------------------------ queries
    def balance(self, cid: int) -> int:
        r = self.db.one(
            "SELECT COALESCE(SUM(CASE kind WHEN 'CREDIT' THEN amount_paise ELSE -amount_paise END),0) AS b "
            "FROM transactions WHERE customer_id=? AND status='active'", (cid,))
        return int(r["b"])

    def balances(self) -> dict[int, int]:
        rows = self.db.query(
            "SELECT customer_id, SUM(CASE kind WHEN 'CREDIT' THEN amount_paise ELSE -amount_paise END) AS b "
            "FROM transactions WHERE status='active' GROUP BY customer_id")
        out = {cid: 0 for cid in self._customers}
        out.update({r["customer_id"]: int(r["b"]) for r in rows})
        return out

    def sum_kind(self, kind: str, start: date, end: date) -> tuple[int, int]:
        """(total paise, count) for kind with txn_date in [start, end]."""
        r = self.db.one(
            "SELECT COALESCE(SUM(amount_paise),0) AS s, COUNT(*) AS n FROM transactions "
            "WHERE status='active' AND kind=? AND txn_date BETWEEN ? AND ?",
            (kind, start.isoformat(), end.isoformat()))
        return int(r["s"]), int(r["n"])

    def total_outstanding(self) -> int:
        return sum(b for b in self.balances().values() if b > 0)

    def top_debtors(self, n: int = 5) -> list[tuple[Customer, int]]:
        bal = sorted(((cid, b) for cid, b in self.balances().items() if b > 0), key=lambda x: -x[1])
        return [(self._customers[cid], b) for cid, b in bal[:n] if cid in self._customers]

    def last_txn(self, cid: int, kind: str | None = None) -> Txn | None:
        sql = "SELECT id FROM transactions WHERE customer_id=? AND status='active'"
        params: list = [cid]
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        sql += " ORDER BY txn_date DESC, id DESC LIMIT 1"
        r = self.db.one(sql, tuple(params))
        return self.txn(r["id"]) if r else None

    def customer_txns(self, cid: int, limit: int = 50) -> list[dict]:
        rows = self.db.query(
            "SELECT * FROM transactions WHERE customer_id=? ORDER BY id DESC LIMIT ?", (cid, limit))
        return [self._row_dict(r) for r in rows]

    def recent_txns(self, limit: int = 15) -> list[dict]:
        rows = self.db.query("SELECT * FROM transactions ORDER BY id DESC LIMIT ?", (limit,))
        return [self._row_dict(r) for r in rows]

    def _row_dict(self, r) -> dict:
        cust = self._customers.get(r["customer_id"])
        return {
            "id": r["id"], "customer_id": r["customer_id"], "customer": cust.name if cust else "?",
            "kind": r["kind"], "amount_paise": r["amount_paise"], "txn_date": r["txn_date"],
            "created_at": r["created_at"], "status": r["status"], "void_reason": r["void_reason"],
            "replaces": r["replaces"], "replaced_by": r["replaced_by"], "source": r["source"],
            "txn_time": r["txn_time"],
        }

    def day_txns(self, d: date, limit: int = 100) -> list[dict]:
        """Active entries of one day, in time order."""
        rows = self.db.query(
            "SELECT * FROM transactions WHERE txn_date=? AND status='active' ORDER BY COALESCE(txn_time,'99:99'), id LIMIT ?",
            (d.isoformat(), limit))
        return [self._row_dict(r) for r in rows]

    def total_owed_by_shop(self) -> tuple[int, int]:
        neg = [-b for b in self.balances().values() if b < 0]
        return sum(neg), len(neg)

    def day_report(self, d: date) -> dict:
        credit, ncredit = self.sum_kind("CREDIT", d, d)
        paid, npaid = self.sum_kind("PAYMENT", d, d)
        return {"date": d.isoformat(), "credit": credit, "credit_count": ncredit, "payments": paid,
                "payments_count": npaid, "entries": self.day_txns(d)}

    # ------------------------------------------------------------------ settings
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        r = self.db.one("SELECT value FROM app_settings WHERE key=?", (key,))
        return r["value"] if r else default

    def set_setting(self, key: str, value: str) -> None:
        with self.db.transaction() as db:
            db.conn.execute("DELETE FROM app_settings WHERE key=?", (key,))
            db.conn.execute("INSERT INTO app_settings(key,value) VALUES(?,?)", (key, value))

    # -------------------------------------------------------------------- alarms
    def add_alarm(self, due_at: datetime, text: str, customer_id: int | None = None,
                  session_id: str | None = None) -> int:
        with self.db.transaction() as db:
            cur = db.conn.execute(
                "INSERT INTO alarms(due_at,text_enc,customer_id,status,created_at) VALUES(?,?,?,'pending',?)",
                (due_at.isoformat(), db.crypto.enc(text), customer_id, now_ist().isoformat()))
            self._audit(db, "ALARM_SET", None, customer_id, session_id, {"due": due_at.isoformat()})
            return cur.lastrowid

    def _alarm_dict(self, r) -> dict:
        cust = self._customers.get(r["customer_id"]) if r["customer_id"] else None
        return {"id": r["id"], "due_at": r["due_at"], "text": self.db.crypto.dec(r["text_enc"]),
                "customer_id": r["customer_id"], "customer": cust.name if cust else None, "status": r["status"]}

    def alarms(self, status: str = "pending") -> list[dict]:
        rows = self.db.query("SELECT * FROM alarms WHERE status=? ORDER BY due_at", (status,))
        return [self._alarm_dict(r) for r in rows]

    def due_alarms(self, now: datetime | None = None) -> list[dict]:
        now = now or now_ist()
        return [a for a in self.alarms() if datetime.fromisoformat(a["due_at"]) <= now]

    def finish_alarm(self, alarm_id: int, status: str = "done") -> bool:
        with self.db.transaction() as db:
            cur = db.conn.execute("UPDATE alarms SET status=? WHERE id=? AND status='pending'", (status, alarm_id))
            return cur.rowcount > 0

    def customer_summary(self, cid: int) -> dict:
        r = self.db.one(
            "SELECT COALESCE(SUM(CASE WHEN kind='CREDIT' THEN amount_paise END),0) AS cr, "
            "COALESCE(SUM(CASE WHEN kind='PAYMENT' THEN amount_paise END),0) AS pay, MAX(txn_date) AS last "
            "FROM transactions WHERE customer_id=? AND status='active'", (cid,))
        c = self._customers[cid]
        return {"id": cid, "name": c.name, "name_hi": c.name_hi, "phone": c.phone,
                "reminder_opt_in": c.reminder_opt_in, "total_credit": int(r["cr"]),
                "total_payments": int(r["pay"]), "balance": int(r["cr"]) - int(r["pay"]),
                "last_txn_date": r["last"]}

    def dashboard(self) -> dict:
        t = today_ist()
        credit, ncredit = self.sum_kind("CREDIT", t, t)
        paid, npaid = self.sum_kind("PAYMENT", t, t)
        top = [{"id": c.id, "name": c.name, "balance": b} for c, b in self.top_debtors(5)]
        owe, nowe = self.total_owed_by_shop()
        y = t - timedelta(days=1)
        return {
            "date": t.isoformat(), "today_credit": credit, "today_credit_count": ncredit,
            "today_payments": paid, "today_payments_count": npaid,
            "total_outstanding": self.total_outstanding(), "customers": len(self._customers),
            "shop_owes": owe, "shop_owes_count": nowe,
            "top_debtors": top, "recent": self.recent_txns(12),
            "today": self.day_report(t), "yesterday": self.day_report(y),
            "alarms": self.alarms(),
        }

    # ---------------------------------------------------------------- reminders
    def save_reminder(self, cid: int, message: str) -> int:
        with self.db.transaction() as db:
            cur = db.conn.execute("INSERT INTO reminders(customer_id,created_at,message_enc) VALUES(?,?,?)",
                                  (cid, now_ist().isoformat(), db.crypto.enc(message)))
            self._audit(db, "REMINDER_DRAFTED", None, cid, None, {})
            return cur.lastrowid

    # -------------------------------------------------------------- transcripts
    def log_transcript(self, session_id: str, role: str, text: str, lang: str | None = None,
                       latency_ms: int | None = None) -> None:
        self.db.execute(
            "INSERT INTO transcripts(session_id,ts,role,lang,text_enc,latency_ms) VALUES(?,?,?,?,?,?)",
            (session_id, now_ist().isoformat(), role, lang, self.db.crypto.enc(text), latency_ms))

    def purge_transcripts(self) -> int:
        cur = self.db.execute("DELETE FROM transcripts")
        return cur.rowcount

    def audit_entries(self, limit: int = 100) -> list[dict]:
        rows = self.db.query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
        return [{"id": r["id"], "ts": r["ts"], "action": r["action"], "txn_id": r["txn_id"],
                 "customer_id": r["customer_id"],
                 "details": json.loads(self.db.crypto.dec(r["details_enc"]) or "{}")} for r in rows]

    def _audit(self, db: Database, action: str, txn_id, customer_id, session_id, details: dict) -> None:
        db.conn.execute(
            "INSERT INTO audit_log(ts,action,txn_id,customer_id,session_id,details_enc) VALUES(?,?,?,?,?,?)",
            (now_ist().isoformat(), action, txn_id, customer_id, session_id,
             db.crypto.enc(json.dumps(details, ensure_ascii=False))))
