"""Rule-based parser: one utterance -> list of Clauses (multi-transaction aware).

"Ramesh ka 340 udhaar, kal 200 diya tha"  ->  [TXN credit 340 today, TXN payment 200 yesterday]
"340 nahi 430"                             ->  [CORRECTION amount 340->430]
"Ramesh ka total?"                         ->  [QUERY BALANCE Ramesh]

No LLM, no network. Runs in well under a millisecond, deterministic and unit-tested.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from . import lexicon as L
from .names import Mention, find_mentions, find_unknown_name
from .normalize import SEP, tokenize
from .numbers import NumberSpan, find_numbers
from .romanize import has_devanagari, has_kannada, pkey
from ..timeutil import month_start, week_start


@dataclass
class Clause:
    intent: str                                  # TXN QUERY CORRECTION UNDO FUTURE NEGATION REMINDER YES NO GREETING UNKNOWN
    tokens: list[str]
    kind: str | None = None                      # CREDIT / PAYMENT
    kind_explicit: bool = False
    amount: int | None = None                    # paise
    amount_flags: set[str] = field(default_factory=set)
    mention: Mention | None = None
    date: date | None = None
    date_explicit: bool = False
    period: tuple[date, date] | None = None
    period_label: str | None = None
    query: str | None = None
    top_n: int | None = None
    # correction payload: new values (and the old amount, used to pick which txn)
    new_amount: int | None = None
    old_amount: int | None = None
    new_mention: Mention | None = None
    new_date: date | None = None
    new_kind: str | None = None
    ordinal: int | None = None
    confidence: float = 1.0
    # customer management (LLM path): add / rename
    new_name: str | None = None
    name_hi: str | None = None
    phone: str | None = None

    @property
    def text(self) -> str:
        return " ".join(self.tokens)


@dataclass
class Parse:
    clauses: list[Clause]
    tokens: list[str]
    lang_hint: str


_HINDI_FUNCTION = {pkey(w) for w in "ka ki ke ne ko hai hain tha hua hue mein kitna kitne kitni kal aaj aur udhaar diya diye likh do nahi hafte mere".split()}


_KANNADA_FUNCTION = {pkey(w) for w in ("udri kottru kottaru kotte kotru ninne monne ivattu eshtu ottu illa beda "
                                        "houdu haudu sari avru avrige saavira nooru munnooru innooru ainooru "
                                        "rupaayi kodtaare naale yaaru jaasti tagondru togondru alla tappu avarinda avrinda tagondu "
                                        "bareyiri barko haaku hoytu aaytu ide").split()}


def _lang_hint(text: str, tokens: list[str]) -> str:
    if has_kannada(text):
        return "kn"
    if has_devanagari(text):
        return "hi"
    keys = {pkey(t) for t in tokens}
    kn, hi = len(keys & _KANNADA_FUNCTION), len(keys & _HINDI_FUNCTION)
    if kn and kn >= hi:
        return "kn"
    return "hi" if hi else "en"


# ---------------------------------------------------------------- segmentation
def _segments(tokens: list[str], spans: list[NumberSpan], mentions: list[Mention]) -> list[tuple[int, int]]:
    segs: list[tuple[int, int]] = []
    lo = 0
    for i, t in enumerate(tokens + [SEP]):
        if t == SEP:
            if i > lo:
                segs.append((lo, i))
            lo = i + 1

    def amounts_in(a: int, b: int) -> list[NumberSpan]:
        return [s for s in spans if a <= s.start < b]

    def inside_span(i: int) -> bool:
        return any(s.start <= i < s.end for s in spans)

    # split on connectors when both sides carry an amount
    out: list[tuple[int, int]] = []
    for a, b in segs:
        cut = a
        for i in range(a, b):
            if tokens[i] in L.CONNECTOR_SPLIT and not inside_span(i):
                if amounts_in(cut, i) and amounts_in(i + 1, b):
                    out.append((cut, i))
                    cut = i + 1
        out.append((cut, b))

    # split unpunctuated multi-amount segments ("ramesh ka 340 udhaar kal 200 diya")
    final: list[tuple[int, int]] = []
    for a, b in out:
        while True:
            amts = amounts_in(a, b)
            if len(amts) < 2:
                break
            first, second = amts[0], amts[1]
            between = [pkey(t) for t in tokens[first.end:second.start]]
            before_first = [pkey(t) for t in tokens[a:first.start]]
            if any(k in L.NEG or k in L.CORRECTION for k in between + before_first[-1:]):
                break  # "340 nahi 430" is a correction, keep together
            cut = None
            for i in range(first.end, second.start):
                k = pkey(tokens[i])
                if k in L.TODAY or k in L.KAL or k in L.PARSO or k in L.WEEKDAYS or \
                        any(m.start == i for m in mentions):
                    cut = i
                    break
            if cut is None:
                for i in range(first.end, second.start):
                    k = pkey(tokens[i])
                    if k in L.CREDIT_STRONG or k in L.CREDIT_WEAK or k in L.PAYMENT_STRONG or \
                            k in L.PAYMENT_VERB or k in L.TAKE_VERB:
                        cut = i + 1
                        # swallow auxiliaries: "diya tha", "likh do"
                        while cut < second.start and pkey(tokens[cut]) in {pkey(x) for x in ("tha", "thi", "the", "hai", "do", "de", "dena", "kar", "karo", "diya", "gaya")}:
                            cut += 1
                        break
            if cut is None:
                cut = second.start
            final.append((a, cut))
            a = cut
        final.append((a, b))

    # merge a bare correction ("nahi nahi") with the value segment that follows ("350")
    merged: list[tuple[int, int]] = []
    i = 0
    while i < len(final):
        a, b = final[i]
        keys = {pkey(t) for t in tokens[a:b]}
        seg_keys = [pkey(t) for t in tokens[a:b] if t != SEP]
        filler = {pkey(x) for x in ("arre", "are", "sorry", "hai", "tha", "ji", "bhai", "nahi", "nahin")}
        only_corr = bool(keys) and keys <= (L.NEG | L.CORRECTION | filler) and bool(keys & (L.NEG | L.CORRECTION))
        ends_neg = bool(seg_keys) and (seg_keys[-1] in L.NEG or seg_keys[-1] in L.CORRECTION) and len(seg_keys) <= 3
        if (only_corr or ends_neg) and i + 1 < len(final):
            na, nb = final[i + 1]
            merged.append((a, nb))  # SEP between them is harmless for parsing
            i += 2
            continue
        merged.append((a, b))
        i += 1
    # an inline correction directly after a txn segment belongs to it: "300 udhaar, nahi 350"
    return merged


# ------------------------------------------------------------------- dates
def _txn_date(toks: list[str], spans: list[NumberSpan], today: date) -> tuple[date | None, bool, int | None]:
    """Returns (date, explicit, token_index_of_date_word)."""
    keys = [pkey(t) for t in toks]
    for i, k in enumerate(keys):
        if k in L.PARSO:
            return today - timedelta(days=2), True, i
        if k == pkey("day") and i + 2 < len(keys) and keys[i + 1] == pkey("before") and keys[i + 2] == pkey("yesterday"):
            return today - timedelta(days=2), True, i
        if k in L.KAL:
            return today - timedelta(days=1), True, i
        if k in L.TODAY:
            return today, True, i
        if k in L.WEEKDAYS:
            wd = L.WEEKDAYS[k]
            delta = (today.weekday() - wd) % 7 or 7
            return today - timedelta(days=delta), True, i
        if k in L.DIN and i + 1 < len(keys) and keys[i + 1] in L.PEHLE:
            for s in spans:
                if s.end == i:
                    return today - timedelta(days=int(s.paise // 100)), True, i
    return None, False, None


def _period(toks: list[str], today: date) -> tuple[tuple[date, date] | None, str | None]:
    keys = [pkey(t) for t in toks]
    prev = any(k in L.PREV for k in keys)
    if any(k in L.WEEK for k in keys):
        ws = week_start(today)
        if prev:
            return (ws - timedelta(days=7), ws - timedelta(days=1)), "last_week"
        return (ws, today), "this_week"
    if any(k in L.MONTH for k in keys):
        ms = month_start(today)
        if prev:
            pm_end = ms - timedelta(days=1)
            return (month_start(pm_end), pm_end), "last_month"
        return (ms, today), "this_month"
    d, explicit, _ = _txn_date(toks, [], today)
    if explicit and d:
        label = {0: "today", 1: "yesterday", 2: "day_before"}.get((today - d).days, "date")
        return (d, d), label
    return None, None


# ------------------------------------------------------------------- kind
_AUX = {pkey(x) for x in ("tha", "thi", "the", "hai", "hain")}


def _kind(keys: list[str], particle: str | None) -> tuple[str | None, bool]:
    ks = set(keys)
    strong_pay = bool(ks & L.PAYMENT_STRONG)
    strong_credit = bool(ks & L.CREDIT_STRONG)
    if strong_pay:
        return "PAYMENT", True
    if strong_credit:
        return "CREDIT", True
    if ks & L.PAYMENT_VERB:
        return ("CREDIT" if particle in L.KO_SET else "PAYMENT"), True
    if ks & L.TAKE_VERB:
        return ("PAYMENT" if particle in L.SE_SET else "CREDIT"), True
    if ks & L.CREDIT_WEAK:
        return "CREDIT", True
    return None, False


def _particle_after(tokens: list[str], m: Mention | None) -> str | None:
    if m is None:
        return None
    if m.particle:
        return m.particle
    j = m.end
    while j < len(tokens) and pkey(tokens[j]) == pkey("ji"):
        j += 1
    return pkey(tokens[j]) if j < len(tokens) else None


# ------------------------------------------------------------------- main
def parse(text: str, customers, today: date) -> Parse:
    tokens = tokenize(text)
    all_spans = find_numbers(tokens)
    # numbers that are day counts ("2 din pehle") are dates, not amounts
    spans = [s for s in all_spans if not (s.end < len(tokens) and pkey(tokens[s.end]) in L.DIN)]
    mentions = find_mentions(tokens, customers)
    clauses: list[Clause] = []
    for a, b in _segments(tokens, spans, mentions):
        c = _parse_segment(tokens, a, b, spans, mentions, today, all_spans)
        if c is not None:
            clauses.append(c)
    _attach_inline_corrections(clauses)
    return Parse(clauses=clauses, tokens=tokens, lang_hint=_lang_hint(text, tokens))


def _attach_inline_corrections(clauses: list[Clause]) -> None:
    """'Ramesh ka 300 udhaar, nahi 350' -> fix the earlier clause before anything is written."""
    i = 1
    while i < len(clauses):
        c, prev = clauses[i], clauses[i - 1]
        if c.intent == "CORRECTION" and prev.intent == "TXN":
            if c.new_amount:
                prev.amount = c.new_amount
                prev.amount_flags = set()
            if c.new_mention:
                prev.mention = c.new_mention
            if c.new_date:
                prev.date, prev.date_explicit = c.new_date, True
            if c.new_kind:
                prev.kind, prev.kind_explicit = c.new_kind, True
            del clauses[i]
            continue
        i += 1


def _parse_segment(tokens, a, b, spans, mentions, today, all_spans=None) -> Clause | None:
    toks = [t for t in tokens[a:b] if t != SEP]
    if not toks:
        return None
    keys = [pkey(t) for t in tokens[a:b]]
    kset = set(keys)
    seg_spans = [s for s in spans if a <= s.start < b]
    seg_mentions = [m for m in mentions if a <= m.start < b]
    c = Clause(intent="UNKNOWN", tokens=toks)

    date_spans = [s for s in (all_spans or spans) if a <= s.start < b]
    if not (kset & L.DIN):
        for k in keys:
            if k in L.ORDINALS:
                c.ordinal = L.ORDINALS[k]

    # --- guardrails: no lending/interest, no pressure language ---------------------
    if kset & L.LENDING:
        c.intent = "REFUSE_LENDING"
        return c
    if kset & L.THREAT:
        c.intent = "REFUSE_PRESSURE"
        return c

    # --- corrections / negations -------------------------------------------------
    corr_idx = [a + i for i, k in enumerate(keys) if k in L.NEG or k in L.CORRECTION]
    if corr_idx:
        p = corr_idx[-1]
        nxt = [pkey(t) for t in tokens[p + 1:min(b, p + 3)] if t != SEP]
        verbish = L.PAYMENT_VERB | L.TAKE_VERB | L.PAYMENT_STRONG | {pkey("kiya"), pkey("kiye"), pkey("hua"), pkey("hue")}
        after_spans = [s for s in seg_spans if s.start > p]
        before_spans = [s for s in seg_spans if s.end <= p]
        after_m = [m for m in seg_mentions if m.start > p]
        before_m = [m for m in seg_mentions if m.end <= p]
        after_keys = [pkey(t) for t in tokens[p + 1:b]]
        before_keys = [pkey(t) for t in tokens[a:p]]
        new_date, date_exp, _ = _txn_date(
            tokens[p + 1:b], [type(x)(x.start - p - 1, x.end - p - 1, x.paise, x.flags)
                              for x in date_spans if x.start > p], today)
        new_kind, kind_exp = _kind(after_keys, None)
        sep_after = p + 1 < b and tokens[p + 1] == SEP
        before_kind_only, _ = _kind(before_keys, None)
        kind_flip = bool(before_kind_only and kind_exp and new_kind != before_kind_only)
        if nxt and nxt[0] in verbish and not after_spans and not after_m and not sep_after and not kind_flip:
            c.intent = "NEGATION"
            c.mention = seg_mentions[0] if seg_mentions else None
            return c
        has_new = bool(after_spans or after_m or date_exp or kind_exp)
        if not has_new:
            if kset <= (L.NEG | L.CORRECTION | L.YES | {pkey("ji"), pkey("bhai")}):
                c.intent = "NO"
                return c
            # "Ramesh ka 340 nahi" etc.: unclear; treat as NO to any pending question
            c.intent = "NO"
            c.mention = seg_mentions[0] if seg_mentions else None
            return c
        before_kind, _ = _kind(before_keys, _particle_after(tokens, before_m[0] if before_m else None))
        inline_txn = bool(seg_spans) and bool(before_m or before_kind) and bool(before_spans or before_m)
        if inline_txn:
            # Self-correction inside one sentence: build a TXN from the corrected values.
            m = after_m[0] if after_m else (before_m[0] if before_m else None)
            amt_span = after_spans[0] if after_spans else (before_spans[0] if before_spans else None)
            kind, kexp = (new_kind, True) if kind_exp else _kind(keys, _particle_after(tokens, m))
            d, dexp, _ = _txn_date(tokens[a:b], [type(x)(x.start - a, x.end - a, x.paise, x.flags) for x in date_spans], today)
            if date_exp:
                d, dexp = new_date, True
            return _finish_txn(c, kind, kexp, amt_span, m, d, dexp, today)
        c.intent = "CORRECTION"
        c.new_amount = after_spans[0].paise if after_spans else None
        c.old_amount = before_spans[-1].paise if before_spans else None
        c.new_mention = after_m[0] if after_m else None
        if not c.new_mention and not after_m:
            unk = find_unknown_name(tokens, p + 1, b)
            if unk and not after_spans:
                c.new_mention = unk
        c.mention = before_m[0] if before_m else None
        c.new_date = new_date if date_exp else None
        c.new_kind = new_kind if kind_exp else None
        return c

    # --- undo ---------------------------------------------------------------------
    if kset & L.UNDO:
        c.intent = "UNDO"
        c.mention = seg_mentions[0] if seg_mentions else None
        c.amount = seg_spans[0].paise if seg_spans else None
        return c

    # --- future promise: never write ---------------------------------------------
    if kset & L.FUTURE:
        c.intent = "FUTURE"
        c.mention = seg_mentions[0] if seg_mentions else None
        c.amount = seg_spans[0].paise if seg_spans else None
        return c

    # --- reminder -------------------------------------------------------------------
    if kset & L.REMINDER:
        c.intent = "REMINDER"
        c.mention = seg_mentions[0] if seg_mentions else find_unknown_name(tokens, a, b)
        return c

    mention = seg_mentions[0] if seg_mentions else None
    particle = _particle_after(tokens, mention)
    kind, kexp = _kind(keys, particle)
    is_query = bool(kset & (L.QUERY | L.TOP | L.MOST)) or (bool(kset & L.WHEN))

    # --- transaction --------------------------------------------------------------
    if seg_spans and not (is_query and (not kexp or kset & (L.TOP | L.MOST | L.QUERY))):
        if mention is None:
            unk = find_unknown_name(tokens, a, b)
            mention = unk
            particle = _particle_after(tokens, mention)
            kind, kexp = _kind(keys, particle)
        d, dexp, _ = _txn_date(tokens[a:b], [type(x)(x.start - a, x.end - a, x.paise, x.flags) for x in date_spans], today)
        # "2 din pehle": the 2 is a date, not the amount
        amt_spans = [s for s in seg_spans if not (s.end < b and pkey(tokens[s.end]) in L.DIN)]
        amt = max(amt_spans, key=lambda s: (s.has_currency, s.paise)) if len(amt_spans) > 1 else (amt_spans[0] if amt_spans else None)
        if amt is not None:
            return _finish_txn(c, kind, kexp, amt, mention, d, dexp, today)

    # --- yes / greeting -------------------------------------------------------------
    if kset <= (L.YES | {pkey("ji"), pkey("bhai"), pkey("kar"), pkey("do"), pkey("de")}) and kset & L.YES:
        c.intent = "YES"
        return c
    if kset & L.GREETING and not seg_spans and not seg_mentions:
        c.intent = "GREETING"
        return c

    # --- an action verb but no amount: "Gupta ji ka udhaar likho" -> ask how much ----------
    action = kset & (L.CREDIT_WEAK | L.PAYMENT_VERB | L.TAKE_VERB | {pkey("jama"), pkey("payment")})
    if action and kexp and not seg_spans and not is_query:
        c.intent = "TXN"
        c.kind, c.kind_explicit = kind, True
        c.mention = mention or find_unknown_name(tokens, a, b)
        d, dexp, _ = _txn_date(tokens[a:b], [], today)
        c.date, c.date_explicit = d or today, dexp
        c.confidence = 0.9
        return c

    # --- queries ----------------------------------------------------------------------
    period, plabel = _period(tokens[a:b], today)
    top_n = None
    for s in seg_spans:
        top_n = int(s.paise // 100)
    if mention is not None and mention.known:
        c.mention = mention
        if kset & (L.LAST | L.WHEN):
            c.query = {"PAYMENT": "LAST_PAYMENT", "CREDIT": "LAST_CREDIT"}.get(kind or "", "LAST_TXN")
        else:
            c.query = "BALANCE"
    elif kset & L.MOST or kset & L.TOP:
        c.query = "TOP_DEBTORS"
        c.top_n = top_n or (5 if kset & L.TOP else 1)
    elif kset & L.CUSTOMERS and kset & L.QUERY and not (kset & (L.CREDIT_STRONG | L.OUTSTANDING)):
        c.query = "CUSTOMER_COUNT"
    elif kset & L.WHO_LIST and (kset & L.CREDIT_STRONG) and not period:
        c.query = "TOP_DEBTORS"
        c.top_n = 5
    elif period and kind == "PAYMENT":
        c.query = "PERIOD_PAYMENTS"
    elif period and kind == "CREDIT":
        c.query = "PERIOD_CREDIT"
    elif period and (kset & L.SUMMARY or kset & L.QUERY):
        c.query = "PERIOD_SUMMARY"
    elif kset & (L.OUTSTANDING | L.ALL) or (kind == "CREDIT" and kset & L.QUERY):
        c.query = "TOTAL_OUTSTANDING"
    elif kset & L.SUMMARY:
        c.query = "PERIOD_SUMMARY"
        period, plabel = (today, today), "today"
    elif mention is not None and not mention.known and kset & L.QUERY:
        c.mention = mention
        c.query = "BALANCE"
    if c.query:
        c.intent = "QUERY"
        c.period, c.period_label = period, plabel
        c.kind = kind
        return c

    if seg_mentions and not seg_spans:
        # bare name: "Ramesh?" -> balance, or an answer to a clarification question
        c.intent = "QUERY"
        c.query = "BALANCE"
        c.mention = seg_mentions[0]
        return c
    if kexp and not seg_spans:
        # "Ramesh ka udhaar likho" (no amount) -> TXN missing amount
        c.intent = "TXN"
        c.kind, c.kind_explicit = kind, True
        c.mention = mention or find_unknown_name(tokens, a, b)
        c.date, c.date_explicit, _ = _txn_date(tokens[a:b], [], today)
        c.date = c.date or today
        c.confidence = 0.5
        return c
    if c.ordinal is not None:
        c.intent = "YES"
        return c
    if not seg_spans:
        unk = find_unknown_name(tokens, a, b)
        if unk:
            c.mention = unk
    return c


def _finish_txn(c: Clause, kind, kexp, amt: NumberSpan | None, mention, d, dexp, today) -> Clause:
    c.intent = "TXN"
    c.kind = kind or "CREDIT"
    c.kind_explicit = bool(kexp)
    c.mention = mention
    c.date = d or today
    c.date_explicit = dexp
    conf = 0.97
    if amt is not None:
        c.amount = amt.paise
        c.amount_flags = set(amt.flags)
        if "colloquial_hundreds" in amt.flags:
            conf -= 0.1
        if "dangling_fraction" in amt.flags:
            conf -= 0.4
        if "decimal" in amt.flags:
            conf -= 0.05
        if amt.paise >= 50_000 * 100:
            conf -= 0.35
        if amt.paise < 100:  # under one rupee
            conf -= 0.4
    else:
        conf = 0.5
    if not kexp:
        conf -= 0.15
    c.confidence = round(max(conf, 0.0), 2)
    return c
