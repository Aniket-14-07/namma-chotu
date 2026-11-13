"""Dialogue manager: parsed clauses -> ledger actions -> one short spoken reply.

State machine per session
  IDLE --(ambiguous name / new name / missing amount / low confidence / overpay)--> PENDING(question)
  PENDING --(answer)--> resume the blocked clause and any clauses queued behind it
  PENDING --(unrelated new command)--> drop question, process the new command
Writes are committed immediately and read back ("commit + spoken correction"), so
"nahi, 430" right after fixes the entry, with the original kept in the audit trail.
"""
from __future__ import annotations

import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field

from . import responses as R
from .config import settings
from .ledger import Ledger, Txn
from .nlu.names import Mention
from .nlu.normalize import normalize
from .nlu.parser import Clause, parse
from .timeutil import today_ist

CONTEXT_WINDOW_S = 120      # "aur 150 add karo" refers to the last customer for this long
PENDING_TTL_S = 90
DEDUPE_WINDOW_S = 6
CORRECTION_WINDOW = 10      # how many recent session writes a correction may target


@dataclass
class Item:
    clause: Clause
    customer_id: int | None = None
    confirmed: bool = False
    overpay_ok: bool = False
    new_customer_ok: bool = False
    target_txn: int | None = None   # for corrections / undo


@dataclass
class Pending:
    kind: str                       # which_customer | new_customer | confirm | overpay(flip) | need_kind | need_amount | need_customer
    item: Item
    queue: list[Item]
    candidates: list[int] = field(default_factory=list)
    new_name: str | None = None
    asked: int = 1
    at: float = field(default_factory=time.monotonic)
    question: list = field(default_factory=list)


@dataclass
class Reply:
    display: str
    speak: str
    lang: str
    events: list[dict]
    pending: dict | None
    intents: list[str]
    nlu_ms: float


@dataclass
class _Turn:
    lang: str
    parts: list = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    groups: "OrderedDict[int, list[tuple[Txn, bool]]]" = field(default_factory=OrderedDict)
    utt_customer: int | None = None
    wrote: bool = False


class Session:
    def __init__(self, session_id: str, ledger: Ledger):
        self.id = session_id
        self.ledger = ledger
        self.pending: Pending | None = None
        self.recent_txns: deque[int] = deque(maxlen=CORRECTION_WINDOW)
        self.last_customer: int | None = None
        self.last_customer_at = 0.0
        self.disclosed: set[str] = set()
        self.last_norm = ""
        self.last_norm_at = 0.0
        self.last_turn_wrote = False
        self.seen_utterances: deque[str] = deque(maxlen=200)
        self.lang = settings.greeting_language
        self.preferred = "auto"
        self.history: deque[tuple[str, str]] = deque(maxlen=8)   # (user|agent, text) for the LLM

    def llm_context(self) -> dict:
        last = self._recent_customer()
        return {"history": list(self.history),
                "last_customer": self._customer(last).name if last and last in self.ledger._customers else None,
                "pending": " ".join(str(x) for x in self.pending.question if isinstance(x, str)) if self.pending else None,
                "lang": self.preferred if self.preferred != "auto" else None}

    # ------------------------------------------------------------------ public
    def set_language(self, lang: str) -> None:
        """Shopkeeper's primary language: replies always use it. 'auto' = reply in the speaker's language."""
        if lang in ("hi", "kn", "en"):
            self.lang = lang
            self.preferred = lang
        elif lang == "auto":
            self.preferred = "auto"

    def greeting(self) -> Reply:
        lang = self.lang
        self.disclosed.add(lang)
        disp, speak = R.render(R.greeting(lang), lang)
        return Reply(disp, speak, lang, [], None, ["GREETING"], 0.0)

    def handle(self, text: str, detected_lang: str | None = None, utterance_id: str | None = None,
               clauses: list[Clause] | None = None) -> Reply | None:
        t0 = time.perf_counter()
        if utterance_id:
            if utterance_id in self.seen_utterances:
                return None
            self.seen_utterances.append(utterance_id)
        text = (text or "").strip()
        if not text:
            return None

        parsed = parse(text, self.ledger.customers, today_ist())
        if self.preferred != "auto":
            lang = self.preferred     # understands hi/kn/en, always answers in the shopkeeper's language
        elif len(parsed.tokens) <= 3 and not detected_lang and parsed.lang_hint == "en":
            lang = self.lang          # "haan", "350", "Kumar wale": no language signal -> keep the conversation's
        else:
            lang = self._pick_lang(detected_lang, parsed.lang_hint)
        self.lang = lang
        turn = _Turn(lang=lang)
        clauses = clauses if clauses is not None else parsed.clauses

        norm = normalize(text)
        now = time.monotonic()
        if norm == self.last_norm and now - self.last_norm_at < DEDUPE_WINDOW_S and self.last_turn_wrote:
            turn.parts += R.simple("duplicate", lang)
            return self._finish(turn, ["DUPLICATE"], t0)
        self.last_norm, self.last_norm_at = norm, now

        self.history.append(("user", text))
        intents = [c.intent for c in clauses]
        handled = False
        if self.pending is not None:
            if now - self.pending.at > PENDING_TTL_S:
                self.pending = None
            else:
                handled = self._resolve_pending(clauses, turn)
        if not handled:
            self._run([Item(c) for c in clauses], turn)
        return self._finish(turn, intents, t0)

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _pick_lang(detected: str | None, hint: str) -> str:
        if not detected:
            return hint
        code = detected.split("-")[0].lower()
        if code == "en" and hint in ("hi", "kn"):
            return hint   # romanised Hinglish / Kanglish
        if code in ("hi", "en", "kn"):
            return code
        # Replies exist for hi/kn/en. Languages closer to Hindi get Hindi, others English.
        return "hi" if code in ("mr", "gu", "pa", "bn") else "en"

    def _customer(self, cid: int):
        return self.ledger.customer(cid)

    def _touch_customer(self, cid: int, turn: _Turn) -> None:
        turn.utt_customer = cid
        self.last_customer, self.last_customer_at = cid, time.monotonic()

    def _recent_customer(self) -> int | None:
        if self.last_customer and time.monotonic() - self.last_customer_at < CONTEXT_WINDOW_S:
            return self.last_customer
        return None

    def _finish(self, turn: _Turn, intents: list[str], t0: float) -> Reply:
        self._flush(turn)
        if not turn.parts:
            turn.parts += R.simple("not_understood", turn.lang)
        if turn.lang not in self.disclosed:
            turn.parts = R.disclosure(turn.lang) + turn.parts
            self.disclosed.add(turn.lang)
        disp, speak = R.render(turn.parts, turn.lang)
        self.history.append(("agent", disp.strip()))
        pending = None
        if self.pending:
            p = self.pending
            opts = [{"id": c, "name": self._customer(c).name} for c in p.candidates]
            if p.kind == "need_kind":
                opts = [{"id": "gave", "name": R.t("opt_gave", turn.lang), "say": "udhaar"},
                        {"id": "got", "name": R.t("opt_got", turn.lang), "say": "jama"}]
            pending = {"kind": p.kind, "question": disp, "options": opts}
        self.last_turn_wrote = turn.wrote
        return Reply(disp.strip(), speak.strip(), turn.lang, turn.events, pending, intents,
                     round((time.perf_counter() - t0) * 1000, 2))

    def _flush(self, turn: _Turn) -> None:
        for cid, items in turn.groups.items():
            cust = self._customer(cid)
            txns = [t for t, _ in items]
            corrected = any(c for _, c in items)
            turn.parts += R.txn_group(cust, txns, self.ledger.balance(cid), turn.lang, corrected=corrected)
            turn.parts.append(" ")
        turn.groups.clear()

    def _block(self, turn: _Turn, pending: Pending, question: list) -> None:
        self._flush(turn)
        pending.question = question
        self.pending = pending
        turn.parts += question

    # --------------------------------------------------------------- queue run
    def _run(self, queue: list[Item], turn: _Turn) -> None:
        while queue:
            item = queue.pop(0)
            blocked = self._step(item, queue, turn)
            if blocked:
                return

    def _step(self, item: Item, queue: list[Item], turn: _Turn) -> bool:
        c = item.clause
        lang = turn.lang
        if c.intent == "TXN":
            return self._step_txn(item, queue, turn)
        if c.intent == "QUERY":
            return self._step_query(item, queue, turn)
        if c.intent == "CORRECTION":
            return self._step_correction(item, queue, turn)
        if c.intent == "UNDO":
            return self._step_undo(item, turn)
        if c.intent == "REMINDER":
            return self._step_reminder(item, queue, turn)
        if c.intent == "ADD_CUSTOMER":
            return self._step_add_customer(item, turn)
        if c.intent == "SET_ALARM":
            return self._step_alarm(item, turn)
        if c.intent == "CLOSING_TIME":
            return self._step_closing_time(item, turn)
        if c.intent == "RENAME_CUSTOMER":
            return self._step_rename(item, queue, turn)
        if c.intent == "REMOVE_CUSTOMER":
            return self._step_remove(item, queue, turn)
        if c.intent in ("CHAT", "GREETING", "UNKNOWN") and getattr(c, "reply", None):
            turn.parts.append(c.reply)
            return False
        if c.intent == "TIME":
            from .timeutil import now_ist
            turn.parts += R.now_time(now_ist(), lang)
            return False
        if c.intent == "FUTURE":
            name = R.name_for(self._customer(c.mention.candidates[0]), lang) if c.mention and c.mention.known \
                else R.t("someone", lang)
            turn.parts += R.simple("future", lang, name=name)
            return False
        if c.intent == "REFUSE_LENDING":
            turn.parts += R.simple("refuse_lending", lang)
            return False
        if c.intent == "REFUSE_PRESSURE":
            turn.parts += R.simple("refuse_pressure", lang)
            return False
        if c.intent == "NEGATION":
            turn.parts += R.simple("negation", lang)
            return False
        if c.intent == "NO":
            turn.parts += R.simple("cancelled", lang)
            return False
        if c.intent == "YES":
            turn.parts += R.simple("yes_no_pending", lang)
            return False
        if c.intent == "GREETING":
            turn.parts += R.simple("greeting_reply", lang)
            return False
        return False  # UNKNOWN: _finish adds the help line if nothing else was said

    # ---- customer resolution shared by txn/query/reminder
    def _resolve_customer(self, item: Item, mention: Mention | None, queue: list[Item], turn: _Turn,
                          allow_context: bool, allow_new: bool) -> int | None | bool:
        """Returns customer id, or True if the turn is now blocked on a question, or None if unresolved."""
        if item.customer_id:
            return item.customer_id
        lang = turn.lang
        if mention is not None and mention.known:
            if len(mention.candidates) == 1:
                return mention.candidates[0]
            for ctx in (turn.utt_customer, self._recent_customer()):
                if ctx in mention.candidates:
                    return ctx
            opts = [self._customer(x) for x in mention.candidates]
            first = mention.surface.split()[0].capitalize()
            firsts = {R.name_for(o, lang).split()[0] for o in opts}
            if len(firsts) == 1:
                first = firsts.pop()
            self._block(turn, Pending("which_customer", item, queue, candidates=list(mention.candidates)),
                        R.ask_which(first, opts, lang))
            return True
        if mention is not None and not mention.known:
            name = mention.surface.title()
            if not allow_new:
                turn.parts += R.simple("unknown_customer", lang, name=name)
                return None
            if item.new_customer_ok:
                same = self.ledger.find_by_name(name)
                if same:
                    return same.id
                cust = self.ledger.add_customer(name, name_hi=item.clause.name_hi, session_id=self.id)
                turn.parts += R.simple("new_customer_created", lang, name=cust.name)
                turn.events.append({"type": "customer_created", "customer": {"id": cust.id, "name": cust.name}})
                return cust.id
            self._block(turn, Pending("new_customer", item, queue, new_name=name), R.ask_new_customer(name, lang))
            return True
        if allow_context:
            ctx = turn.utt_customer or self._recent_customer()
            if ctx:
                return ctx
        return None

    # ---- TXN
    def _step_txn(self, item: Item, queue: list[Item], turn: _Turn) -> bool:
        c = item.clause
        lang = turn.lang
        cid = self._resolve_customer(item, c.mention, queue, turn, allow_context=True, allow_new=True)
        if cid is True:
            return True
        if cid is None:
            if c.amount is None:
                turn.parts += R.simple("not_understood", lang)
                return False
            self._block(turn, Pending("need_customer", item, queue), R.ask_customer(c.amount, lang))
            return True
        item.customer_id = cid
        cust = self._customer(cid)
        if c.settle_all and c.amount is None:
            bal = self.ledger.balance(cid)
            if bal <= 0:
                turn.parts += R.simple("already_settled", lang, name=R.name_for(cust, lang))
                return False
            c.kind, c.kind_explicit, c.amount, c.confidence = "PAYMENT", True, bal, 0.95
        if c.amount is None:
            self._block(turn, Pending("need_amount", item, queue), R.ask_amount(R.name_for(cust, lang), c.kind, lang))
            return True
        if c.kind is None:
            # "credit"/"debit" alone, or the LLM couldn't tell who gave: never guess the direction
            self._block(turn, Pending("need_kind", item, queue), R.ask_kind(R.name_for(cust, lang), c.amount, lang))
            return True
        needs_confirm = settings.confirm_mode == "always" or c.confidence < 0.7
        if needs_confirm and not item.confirmed:
            self._block(turn, Pending("confirm", item, queue),
                        R.ask_confirm(R.name_for(cust, lang), c.amount, c.kind or "CREDIT", c.date or today_ist(), lang))
            return True
        if not item.overpay_ok:
            # the balance would flip sides (they owed you -> you owe them, or the reverse): always confirm
            bal = self.ledger.balance(cid) + self._pending_effect(turn, cid)
            new = bal - c.amount if c.kind == "PAYMENT" else bal + c.amount
            if (bal > 0 and new < 0) or (bal < 0 and new > 0):
                self._block(turn, Pending("overpay", item, queue),
                            R.ask_flip(R.name_for(cust, lang), bal, new, c.amount, c.kind, lang))
                return True
        txn = self.ledger.record(cid, c.kind or "CREDIT", c.amount, c.date, session_id=self.id,
                                 confidence=c.confidence, txn_time=c.txn_time)
        self._wrote(turn, txn, "created")
        return False

    def _pending_effect(self, turn: _Turn, cid: int) -> int:
        return 0  # writes are committed immediately, so the ledger balance is already current

    def _wrote(self, turn: _Turn, txn: Txn, action: str, corrected: bool = False) -> None:
        self.recent_txns.append(txn.id)
        turn.groups.setdefault(txn.customer_id, []).append((txn, corrected))
        turn.events.append({"type": "txn", "action": action, "txn": self._txn_dict(txn)})
        turn.wrote = True
        self._touch_customer(txn.customer_id, turn)

    def _txn_dict(self, t: Txn) -> dict:
        return {"id": t.id, "customer_id": t.customer_id, "customer": self._customer(t.customer_id).name,
                "kind": t.kind, "amount_paise": t.amount_paise, "txn_date": t.txn_date, "status": t.status,
                "replaces": t.replaces, "txn_time": t.txn_time}

    # ---- end-of-day / any-day overview
    def summary_parts(self, start, end, label, lang: str, intro: bool = False) -> list:
        L = self.ledger
        cr, n1 = L.sum_kind("CREDIT", start, end)
        pay, n2 = L.sum_kind("PAYMENT", start, end)
        get = L.total_outstanding()
        owe, _ = L.total_owed_by_shop()
        last = None
        if start == end:
            times = [e["txn_time"] for e in L.day_txns(start) if e.get("txn_time")]
            last = max(times) if times else None
        return R.closing_summary(label, start, cr, pay, n1 + n2, get, owe, last, lang, intro=intro)

    # ---- reminders for the shopkeeper
    def _step_alarm(self, item: Item, turn: _Turn) -> bool:
        c = item.clause
        lang = turn.lang
        if c.alarm_at is None:
            turn.parts += R.simple("alarm_need_time", lang)
            return False
        from datetime import timedelta as _td
        from .timeutil import now_ist
        now = now_ist()
        if c.alarm_at <= now and c.alarm_at.hour < 12 and c.alarm_at.date() == now.date() \
                and c.alarm_at + _td(hours=12) > now:
            c.alarm_at = c.alarm_at + _td(hours=12)          # "8 baje" said at 7 pm means 8 pm
        if c.alarm_at <= now:
            turn.parts += R.simple("alarm_past", lang)
            return False
        cid = None
        if c.mention is not None and c.mention.known and len(c.mention.candidates) == 1:
            cid = c.mention.candidates[0]
        text = (c.alarm_text or "").strip() or "—"
        aid = self.ledger.add_alarm(c.alarm_at, text, cid, session_id=self.id)
        turn.events.append({"type": "alarm_set", "alarm": {"id": aid, "due_at": c.alarm_at.isoformat(), "text": text}})
        turn.parts += R.simple("alarm_set", lang, d=R.Day(c.alarm_at.date()),
                               tm=R.time_word(c.alarm_at.strftime("%H:%M"), lang), x=text)
        return False

    def _step_closing_time(self, item: Item, turn: _Turn) -> bool:
        c = item.clause
        lang = turn.lang
        if not c.closing_time:
            turn.parts += R.simple("alarm_need_time", lang)
            return False
        self.ledger.set_setting("closing_time", c.closing_time)
        turn.events.append({"type": "settings", "closing_time": c.closing_time})
        turn.parts += R.simple("closing_set", lang, tm=R.time_word(c.closing_time, lang))
        return False

    def push_reply(self, parts: list, lang: str | None = None) -> Reply:
        """A reply Chotu starts by itself (alarm, closing summary): not tied to a user turn."""
        lang = lang or (self.preferred if self.preferred != "auto" else self.lang)
        disp, speak = R.render(parts, lang)
        self.history.append(("agent", disp.strip()))
        return Reply(disp.strip(), speak.strip(), lang, [], None, ["PUSH"], 0.0)

    # ---- ADD / RENAME customer
    def _created(self, cust, turn: _Turn) -> None:
        turn.events.append({"type": "customer_created", "customer": {"id": cust.id, "name": cust.name}})
        self._touch_customer(cust.id, turn)

    def _step_add_customer(self, item: Item, turn: _Turn) -> bool:
        c = item.clause
        lang = turn.lang
        name = c.new_name or (c.mention.surface if c.mention else None)
        if c.mention is not None and c.mention.known and len(c.mention.candidates) == 1 and not c.new_name:
            turn.parts += R.simple("customer_exists", lang, name=R.name_for(self._customer(c.mention.candidates[0]), lang))
            return False
        if not name:
            turn.parts += R.simple("need_customer_name", lang)
            return False
        same = self.ledger.find_by_name(name)
        if same:
            self._touch_customer(same.id, turn)
            turn.parts += R.simple("customer_exists", lang, name=R.name_for(same, lang))
            return False
        cust = self.ledger.add_customer(name, name_hi=c.name_hi, phone=c.phone, session_id=self.id)
        turn.parts += R.simple("new_customer_created", lang, name=R.name_for(cust, lang))
        self._created(cust, turn)
        return False

    def _step_rename(self, item: Item, queue: list[Item], turn: _Turn) -> bool:
        c = item.clause
        lang = turn.lang
        cid = self._resolve_customer(item, c.mention, queue, turn, allow_context=True, allow_new=False)
        if cid is True:
            return True
        if cid is None:
            turn.parts += R.simple("need_customer_name", lang)
            return False
        if not c.new_name:
            turn.parts += R.simple("need_new_name", lang)
            return False
        other = self.ledger.find_by_name(c.new_name)
        if other and other.id != cid:
            turn.parts += R.simple("customer_exists", lang, name=R.name_for(other, lang))
            return False
        old_name = self._customer(cid).name
        cust = self.ledger.update_customer(cid, name=c.new_name, name_hi=c.name_hi, session_id=self.id)
        turn.events.append({"type": "customer_updated", "old": old_name, "customer": {"id": cust.id, "name": cust.name}})
        self._touch_customer(cid, turn)
        turn.parts += R.simple("customer_renamed", lang, name=R.name_for(cust, lang))
        return False

    def _step_remove(self, item: Item, queue: list[Item], turn: _Turn) -> bool:
        lang = turn.lang
        cid = self._resolve_customer(item, item.clause.mention, queue, turn, allow_context=True, allow_new=False)
        if cid is True:
            return True
        if cid is None:
            turn.parts += R.simple("need_customer_name", lang)
            return False
        cust = self._customer(cid)
        self._flush(turn)                      # say any entry for them first, while they still exist
        try:
            self.ledger.remove_customer(cid, session_id=self.id)
        except ValueError:
            turn.parts += R.simple("remove_not_zero", lang, name=R.name_for(cust, lang)) + R.balance(cust, self.ledger.balance(cid), lang)
            return False
        turn.events.append({"type": "customer_removed", "customer": {"id": cid, "name": cust.name}})
        if self.last_customer == cid:
            self.last_customer = None
        turn.parts += R.simple("customer_removed", lang, name=R.name_for(cust, lang))
        return False

    # ---- QUERY
    def _step_query(self, item: Item, queue: list[Item], turn: _Turn) -> bool:
        c = item.clause
        lang = turn.lang
        L = self.ledger
        q = c.query
        if q in ("BALANCE", "LAST_PAYMENT", "LAST_CREDIT", "LAST_TXN"):
            cid = self._resolve_customer(item, c.mention, queue, turn, allow_context=True, allow_new=False)
            if cid is True:
                return True
            if cid is None:
                if not (c.mention and not c.mention.known):
                    turn.parts += R.simple("not_understood", lang)
                return False
            self._touch_customer(cid, turn)
            cust = self._customer(cid)
            if q == "BALANCE":
                turn.parts += R.balance(cust, L.balance(cid), lang)
            else:
                kind = {"LAST_PAYMENT": "PAYMENT", "LAST_CREDIT": "CREDIT"}.get(q)
                turn.parts += R.last_txn(cust, L.last_txn(cid, kind), kind, lang)
            return False
        if q == "CUSTOMER_HISTORY":
            cid = self._resolve_customer(item, c.mention, queue, turn, allow_context=True, allow_new=False)
            if cid is True:
                return True
            if cid is None:
                q = "LIST_CUSTOMERS"
            else:
                self._touch_customer(cid, turn)
                rows = [e for e in L.customer_txns(cid, 8) if e["status"] == "active"]
                turn.parts += R.customer_history(self._customer(cid), rows, L.balance(cid), lang)
                return False
        if q == "LIST_CUSTOMERS":
            bals = L.balances()
            rows = sorted(((self._customer(cid), b) for cid, b in bals.items() if cid in L._customers),
                          key=lambda x: (-abs(x[1]), x[0].name))
            turn.parts += R.list_customers(rows, lang)
            return False
        t = today_ist()
        start, end = c.period or (t, t)
        label = c.period_label or "today"
        if q == "LIST_ENTRIES":
            entries = []
            d = start
            from datetime import timedelta as _td
            while d <= end and len(entries) < 60:
                entries += L.day_txns(d)
                d += _td(days=1)
            turn.parts += R.list_entries(label, start, entries, lang)
            return False
        if q == "PERIOD_CREDIT":
            total, n = L.sum_kind("CREDIT", start, end)
            turn.parts += R.period_sum("CREDIT", label, start, total, n, lang)
        elif q == "PERIOD_PAYMENTS":
            total, n = L.sum_kind("PAYMENT", start, end)
            turn.parts += R.period_sum("PAYMENT", label, start, total, n, lang)
        elif q == "PERIOD_SUMMARY":
            turn.parts += self.summary_parts(start, end, label, lang)
        elif q == "TOTAL_OUTSTANDING":
            bals = L.balances()
            owing = [b for b in bals.values() if b > 0]
            owe = [-b for b in bals.values() if b < 0]
            turn.parts += R.total_outstanding(sum(owing), len(owing), lang, sum(owe), len(owe))
        elif q == "TOP_DEBTORS":
            turn.parts += R.top_debtors(L.top_debtors(max(1, min(c.top_n or 1, 5))), lang)
        elif q == "CUSTOMER_COUNT":
            bals = L.balances()
            turn.parts += R.customer_count(len(L.customers), sum(1 for b in bals.values() if b > 0), lang)
        else:
            turn.parts += R.simple("not_understood", lang)
        return False

    # ---- CORRECTION
    def _pick_recent(self, amount: int | None = None, customers: list[int] | None = None) -> Txn | None:
        for tid in reversed(self.recent_txns):
            t = self.ledger.txn(tid)
            if t.status != "active":
                continue
            if amount is not None and t.amount_paise != amount:
                continue
            if customers and t.customer_id not in customers:
                continue
            return t
        return None

    def _step_correction(self, item: Item, queue: list[Item], turn: _Turn) -> bool:
        c = item.clause
        lang = turn.lang
        target = self.ledger.txn(item.target_txn) if item.target_txn else None
        if target is None:
            old_custs = c.mention.candidates if (c.mention and c.mention.known) else None
            target = self._pick_recent(c.old_amount, old_custs) or self._pick_recent(None, old_custs) \
                or self._pick_recent()
        if target is None or target.status != "active":
            turn.parts += R.simple("nothing_to_correct", lang)
            return False
        item.target_txn = target.id
        new_cid = None
        if c.new_mention is not None:
            r = self._resolve_customer(item, c.new_mention, queue, turn, allow_context=False, allow_new=True)
            if r is True:
                return True
            new_cid = r
        if item.customer_id:
            new_cid = item.customer_id
        if not any([c.new_amount, new_cid, c.new_date, c.new_kind]):
            turn.parts += R.simple("nothing_to_correct", lang)
            return False
        txn = self.ledger.correct(target.id, customer_id=new_cid, kind=c.new_kind, amount_paise=c.new_amount,
                                  txn_date=c.new_date, session_id=self.id)
        turn.events.append({"type": "txn", "action": "voided", "txn": self._txn_dict(self.ledger.txn(target.id))})
        self._wrote(turn, txn, "corrected", corrected=True)
        if new_cid and new_cid != target.customer_id:
            # the old customer's balance changed too
            old = self._customer(target.customer_id)
            turn.groups.move_to_end(txn.customer_id)
            self._flush(turn)
            turn.parts += [R.name_for(old, lang), ": "] + R.balance_tail(self.ledger.balance(old.id), lang)
        return False

    # ---- UNDO
    def _step_undo(self, item: Item, turn: _Turn) -> bool:
        c = item.clause
        lang = turn.lang
        custs = c.mention.candidates if (c.mention and c.mention.known) else None
        target = self._pick_recent(c.amount, custs) or self._pick_recent(None, custs)
        if target is None and custs and len(custs) == 1:
            last = self.ledger.last_txn(custs[0])
            if last and last.created_at[:10] == today_ist().isoformat():
                target = last
        if target is None:
            turn.parts += R.simple("nothing_to_undo", lang)
            return False
        voided = self.ledger.void(target.id, "voice-undo", session_id=self.id)
        turn.events.append({"type": "txn", "action": "voided", "txn": self._txn_dict(voided)})
        turn.wrote = True
        cust = self._customer(voided.customer_id)
        turn.parts += R.undo_done(cust, voided, self.ledger.balance(cust.id), lang)
        return False

    # ---- REMINDER (opt-in only, polite text, shopkeeper taps to send)
    def _step_reminder(self, item: Item, queue: list[Item], turn: _Turn) -> bool:
        c = item.clause
        lang = turn.lang
        cid = self._resolve_customer(item, c.mention, queue, turn, allow_context=True, allow_new=False)
        if cid is True:
            return True
        if cid is None:
            turn.parts += R.simple("not_understood", lang)
            return False
        cust = self._customer(cid)
        name = R.name_for(cust, lang)
        if not cust.reminder_opt_in:
            turn.parts += R.simple("reminder_no_optin", lang, name=name)
            return False
        bal = self.ledger.balance(cid)
        if bal <= 0:
            turn.parts += R.simple("reminder_zero", lang, name=name)
            return False
        msg = R.reminder_message(cust, bal)
        rid = self.ledger.save_reminder(cid, msg)
        turn.events.append({"type": "reminder", "id": rid, "customer": cust.name, "phone": cust.phone,
                            "message": msg})
        turn.parts += R.simple("reminder_ready", lang, name=name)
        return False

    # ---------------------------------------------------------- pending answers
    def _resolve_pending(self, clauses: list[Clause], turn: _Turn) -> bool:
        p = self.pending
        assert p is not None
        lang = turn.lang
        intents = {c.intent for c in clauses}
        is_yes = "YES" in intents and not ({"TXN", "CORRECTION"} & intents)
        is_no = bool({"NO", "UNDO", "NEGATION"} & intents) and "CORRECTION" not in intents

        def resume() -> bool:
            self.pending = None
            self._run([p.item] + p.queue, turn)
            return True

        def cancel() -> bool:
            self.pending = None
            turn.parts += R.simple("cancelled", lang)
            return True

        def drop() -> bool:
            self.pending = None
            # a new topic simply replaces the open question; no robotic "dropped" notice
            return False

        def reask() -> bool:
            p.at = time.monotonic()
            turn.parts += p.question
            return True

        if p.kind == "which_customer":
            chosen = None
            for c in clauses:
                for m in (c.mention, c.new_mention):
                    if m is not None and m.known:
                        inter = [x for x in m.candidates if x in p.candidates]
                        if len(inter) == 1:
                            chosen = inter[0]
                if chosen is None and c.ordinal is not None and c.ordinal < len(p.candidates):
                    chosen = p.candidates[c.ordinal]
            if chosen:
                if p.item.clause.intent == "CORRECTION":
                    p.item.customer_id = chosen
                else:
                    p.item.customer_id = chosen
                return resume()
            if is_no:
                return cancel()
            if intents & {"TXN", "QUERY", "UNDO", "REMINDER"} and any(
                    c.amount or c.query not in (None, "BALANCE") or (c.mention and c.mention.known) for c in clauses):
                return drop()
            if p.asked >= 2:
                return cancel()
            p.asked += 1
            p.at = time.monotonic()
            turn.parts += p.question
            return True

        if p.kind == "new_customer":
            if is_yes:
                p.item.new_customer_ok = True
                return resume()
            for c in clauses:
                fixed = c.new_name if c.intent in ("ADD_CUSTOMER", "RENAME_CUSTOMER") else None
                if fixed:
                    p.item.clause.mention = Mention(0, 0, [], 0.0, known=False, surface=fixed)
                    p.item.clause.name_hi = c.name_hi
                    p.item.new_customer_ok = True
                    return resume()
            for c in clauses:
                m = c.new_mention or c.mention
                if m is not None and m.known and len(m.candidates) == 1:
                    p.item.customer_id = m.candidates[0]   # "nahi, Ramesh Kumar" = existing customer
                    return resume()
            if is_no:
                return cancel()
            return drop()

        if p.kind in ("confirm", "overpay"):
            if is_yes:
                if p.kind == "confirm":
                    p.item.confirmed = True
                else:
                    p.item.overpay_ok = True
                return resume()
            new_amt = next((c.new_amount for c in clauses if c.intent == "CORRECTION" and c.new_amount), None)
            if new_amt is None:
                bare = [c for c in clauses if c.intent == "TXN" and c.amount and c.mention is None]
                new_amt = bare[0].amount if bare else None
            if new_amt:
                p.item.clause.amount = new_amt
                p.item.confirmed = True
                return resume()
            if is_no:
                return cancel()
            return drop()

        if p.kind == "need_kind":
            kinds = [c.kind for c in clauses if c.kind in ("CREDIT", "PAYMENT")]
            if kinds:
                p.item.clause.kind, p.item.clause.kind_explicit = kinds[0], True
                p.item.confirmed = True
                return resume()
            if is_no:
                return cancel()
            if is_yes:
                return reask()
            return drop()

        if p.kind == "need_amount":
            amt = next((c.amount or c.new_amount for c in clauses if (c.amount or c.new_amount)), None)
            if amt:
                p.item.clause.amount = amt
                p.item.clause.confidence = max(p.item.clause.confidence, 0.9)
                return resume()
            if is_no:
                return cancel()
            if is_yes:
                return reask()
            return drop()

        if p.kind == "need_customer":
            for c in clauses:
                m = c.mention or c.new_mention
                if m is not None:
                    p.item.clause.mention = m
                    return resume()
            if is_no:
                return cancel()
            if is_yes:
                return reask()
            return drop()

        self.pending = None
        return False
