"""LLM understanding layer (any OpenAI-compatible API: Groq, xAI Grok, OpenAI...).

What the LLM does: turn one spoken/typed sentence (Hindi, Kannada, English, code-mixed,
any script) into a list of structured commands, using the conversation so far.
What it never does: compute balances, totals or answers. The deterministic ledger
engine does that, so a hallucination can at worst trigger a confirmation question,
never a wrong balance.

Safety nets
- An amount is trusted (written directly) only if our own number parser also heard
  that number in the sentence; otherwise the dialogue asks "is that right?" first.
- Customer names from the LLM are matched against the real customer list by our own
  fuzzy matcher, never by the LLM.
- Timeout / bad JSON / no key -> the rule parser handles the turn as before.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import timedelta

import httpx

from .config import settings
from .nlu.names import Mention, find_mentions
from .nlu.normalize import tokenize
from .nlu.numbers import find_numbers
from .nlu.parser import Clause
from .timeutil import month_start, today_ist, week_start

log = logging.getLogger("llm")

INTENTS = {"TXN", "QUERY", "CORRECTION", "UNDO", "YES", "NO", "ADD_CUSTOMER", "RENAME_CUSTOMER",
           "GREETING", "FUTURE", "REMINDER", "SET_ALARM", "CLOSING_TIME", "CHAT", "TIME", "REMOVE_CUSTOMER", "UNKNOWN"}
QUERIES = {"BALANCE", "LAST_PAYMENT", "LAST_CREDIT", "PERIOD_CREDIT", "PERIOD_PAYMENTS", "PERIOD_SUMMARY",
           "TOTAL_OUTSTANDING", "TOP_DEBTORS", "CUSTOMER_COUNT", "LIST_CUSTOMERS", "LIST_ENTRIES", "CUSTOMER_HISTORY"}

_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    """One kept-alive client: reusing the TLS connection saves a few hundred ms per turn."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=settings.llm_timeout_s,
                                    limits=httpx.Limits(max_keepalive_connections=4, keepalive_expiry=120))
    return _client

SYSTEM = """You are the language-understanding module of "Namma Chotu", a voice khata (credit ledger) for Indian kirana shops.
The shopkeeper speaks Hindi, Kannada, English or a mix, in any script; speech-to-text may misspell words and names.
Convert the LATEST utterance into JSON commands. Use the conversation context to resolve "he/isko/usko/avrige",
answers to the assistant's last question, and follow-ups like "aur 200".

Return ONLY this JSON:
{"commands":[{
 "intent": "TXN|QUERY|CORRECTION|UNDO|YES|NO|ADD_CUSTOMER|RENAME_CUSTOMER|GREETING|FUTURE|REMINDER|SET_ALARM|CLOSING_TIME|CHAT|UNKNOWN",
 "reply": string|null,           // CHAT / GREETING / UNKNOWN only: what Chotu says back (see Conversation)
 "customer": string|null,        // customer name (Latin letters); null if not said
 "heard_name": string|null,      // the name as literally heard in the utterance
 "customer_ref": "named|previous|none",  // previous = pronoun / the customer just discussed
 "kind": "CREDIT|PAYMENT"|null,
 "amount_rupees": number|null,   // never invent; null if no amount was said
 "days_ago": integer|null,       // kal (past) = 1, parso = 2, ninne = 1; null = today
 "date": "YYYY-MM-DD"|null,      // a specific calendar date that was said ("12 November", "Monday ka")
 "time": "HH:MM"|null,           // 24h clock time said for the entry ("shaam 5 baje" = "17:00"); null if not said
 "alarm_at": "YYYY-MM-DDTHH:MM"|null, // SET_ALARM: when to remind (for reminders "kal" = tomorrow)
 "alarm_text": string|null,      // SET_ALARM: what to remind about, short, in the shopkeeper's language
 "query": "BALANCE|LAST_PAYMENT|LAST_CREDIT|PERIOD_CREDIT|PERIOD_PAYMENTS|PERIOD_SUMMARY|TOTAL_OUTSTANDING|TOP_DEBTORS|CUSTOMER_COUNT|LIST_CUSTOMERS|LIST_ENTRIES|CUSTOMER_HISTORY"|null,
 "period": "today|yesterday|this_week|this_month"|null,
 "new_name": string|null,        // ADD_CUSTOMER / RENAME_CUSTOMER: the correct full name, Latin letters, Title Case
 "name_hi": string|null,         // the same customer name written in Devanagari (for natural Hindi speech)
 "phone": string|null,           // digits only, if a phone number was said for ADD_CUSTOMER
 "new_amount_rupees": number|null // CORRECTION: the corrected amount
}]}

Meaning of kind. Think "WHO OWES WHOM after this sentence", from the shopkeeper's side (do not match keywords):
- CREDIT = "you gave": the customer now owes the shop MORE (or the shop owes them less).
  Goods on credit / udhaar / baaki / "likh do" / ಉದ್ರಿ / shopping on account / cash or loan given TO the customer /
  any statement that the CUSTOMER has to pay: "isko 500 dena hai" (he has to give), "iska 500 udhaar bacha hai",
  "isne 500 ki shopping kari", "isse 500 lena hai" (I have to collect), "Suresh owes 500", "avru 500 kodbeku", "500 barbeku".
- PAYMENT = "you got": the customer now owes LESS (or the shop owes them more).
  Customer paid / jama / wapas / GPay / "ne 500 diye" / advance deposited / ಕೊಟ್ಟರು / ಜಮಾ /
  any statement that the SHOPKEEPER has to pay: "MUJHE isko 500 dena hai", "maine isko 500 dene hain",
  "isko 500 lena hai" (he has to collect from me), "I owe Suresh 500", "naanu avrige 500 kodbeku".
- "dena hai / kodbeku" without mujhe/maine/naanu/I = the CUSTOMER must pay (CREDIT). With them = the SHOPKEEPER must pay (PAYMENT).
- The words "credit" / "debit" / "credited" alone are AMBIGUOUS (shop meaning vs bank meaning): set kind null.
  Also set kind null whenever you cannot tell who gave to whom. Never guess the direction; the app will ask.

Names:
- "customer": the existing customer this refers to (fix STT misspellings ONLY if clearly the same person, e.g. "Rames Kumaar" -> "Ramesh Kumar").
- "heard_name": the name exactly as it appears in the utterance (Latin letters), or null. Never replace a NEW name with a different known one:
  if "Aniket" is said and only "Ankit"/"Amit" exist, customer = "Aniket" (a new person), not Ankit.

Conversation (you are Chotu, a friendly, quick kirana-shop assistant with a brain, not a form):
- Small talk, the time or date, how the app works, light shop/business talk (stock, festivals, handling customers, saving
  money, simple tips) = CHAT with a short spoken "reply": 1-2 sentences, warm, natural, in the SAME language and script
  the shopkeeper used (Hindi in Devanagari, Kannada in Kannada script, English). Gently steer back to the khata when natural.
- "Abhi kitna baja hai / time kya hai" = CHAT; answer from the "Now" line.
- Never state ledger numbers (balances, totals, entries) in "reply": those come only from QUERY.
- Not a shop matter at all (politics, medical, legal, coding...): CHAT, politely say you only help with the shop.
- If the sentence is garbled or you are unsure what was meant, CHAT with a short clarifying question, never UNKNOWN.

Lists:
- "List do / sabka hisaab / kis kis ka baaki hai / customers ki list / sab grahak" = QUERY LIST_CUSTOMERS.
- "Aaj ki entries / kal kya kya hua / entries ki list" = QUERY LIST_ENTRIES with period or date.
- "Ramesh ka pura hisaab / Ramesh ki entries" = QUERY CUSTOMER_HISTORY with customer.

Other rules:
- "Kitna baaki hai / eshtu baaki / how much does X owe" = QUERY BALANCE. "Aaj ka hisaab / sales / ವ್ಯಾಪಾರ / summary" = QUERY PERIOD_SUMMARY (period today unless said).
  "Total kitna udhaar hai bazaar mein" = TOTAL_OUTSTANDING. "Sabse zyada kiska baaki" = TOP_DEBTORS.
- "Nahi, 430 tha / galat, 340 nahi 430" = CORRECTION with new_amount_rupees. "Hata do / cancel / undo / ತೆಗೆ" = UNDO.
- "Naya customer / naya khata / add karo <name>" = ADD_CUSTOMER with new_name.
- "<X> ne saara udhaar chuka diya / cleared all dues" = TXN PAYMENT with settle_all true and amount null.
- "<X> ka naam hata do / ab customer nahi hai / remove X" = REMOVE_CUSTOMER with customer.
  "Cleared everything, remove him" = two commands: TXN PAYMENT settle_all, then REMOVE_CUSTOMER.
- REMINDER = a polite payment reminder to SEND TO A CUSTOMER ("Ramesh ko yaad dila do", "remind Ramesh").
- SET_ALARM = remind the SHOPKEEPER himself at a time ("mujhe shaam 7 baje yaad dilana ki Ramesh se paise lene hain",
  "kal subah 10 baje doodh wale ko call karna yaad dilana"). Fill alarm_at and alarm_text.
- CLOSING_TIME = set the daily end-of-day summary time ("roz raat 9 baje hisaab sunana", "dukaan 10 baje band hoti hai"): put it in "time".
- "Aaj ka hisaab / din ka summary / dukaan band, hisaab batao / kal ka hisaab / 12 tareekh ka hisaab" = QUERY PERIOD_SUMMARY
  with period or date (or days_ago).
- "<X> ka naam <Y> karo / spelling galat hai, <Y> likho / naam badlo" = RENAME_CUSTOMER: customer = X (or previous), new_name = Y.
- When the assistant just asked a yes/no question: haan/ha/ಹೌದು/sari/ok/yes = YES; nahi/ಇಲ್ಲ/beda/no = NO.
- When the assistant just asked for a name or amount, a bare name or number answers it (TXN with only that field).
- When the assistant asked "open a new account for X?" and the shopkeeper says a different/corrected name, return ADD_CUSTOMER with new_name = corrected name.
- Future promise ("kal dega", "will pay tomorrow") = FUTURE. Hello/namaste = GREETING. Anything else = UNKNOWN.
- Several actions in one sentence -> several commands, in order."""


def _ctx_lines(history: list[tuple[str, str]], last_customer: str | None, pending: str | None,
               lang: str | None = None) -> str:
    lines = []
    for role, text in history[-6:]:
        lines.append(f"{'Shopkeeper' if role == 'user' else 'Assistant'}: {text}")
    out = "Conversation so far:\n" + ("\n".join(lines) if lines else "(none)")
    if last_customer:
        out += f"\nCustomer just discussed: {last_customer}"
    if pending:
        out += f"\nThe assistant is waiting for an answer to: {pending}"
    if lang in ("hi", "kn", "en"):
        out += f"\nShopkeeper's chosen language: {dict(hi='Hindi', kn='Kannada', en='English')[lang]} (write any reply in it)"
    return out


async def extract(text: str, customers, *, history: list[tuple[str, str]] | None = None,
                  last_customer: str | None = None, pending: str | None = None,
                  lang: str | None = None) -> list[Clause] | None:
    if not settings.llm_enabled:
        return None
    names = ", ".join(c.name for c in customers)[:3000]
    from .timeutil import now_ist
    now = now_ist()
    user = (f"Now: {now.strftime('%A %Y-%m-%d %H:%M')} (IST)\nKnown customers: {names or '(none yet)'}\n"
            f"{_ctx_lines(history or [], last_customer, pending, lang)}\n\nLATEST utterance: {text}")
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    t0 = time.perf_counter()
    data = await _call(msgs)
    if data is None:
        return None
    log.info("llm %.0f ms: %s", (time.perf_counter() - t0) * 1000, json.dumps(data, ensure_ascii=False)[:400])
    raw = data.get("commands") or data.get("clauses") or []
    if not isinstance(raw, list):
        return None
    return to_clauses(text, raw, customers)


# Groq retires models often; if the configured one is gone, these are tried in order (kept working one is remembered)
FALLBACK_MODELS = ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.6-27b", "llama-3.3-70b-versatile"]
_working_model: str | None = None
last_error: str | None = None


def _parse_json(content: str) -> dict | None:
    content = (content or "").strip()
    if content.startswith("```"):
        content = content.strip("`").split("\n", 1)[-1]
    a, b = content.find("{"), content.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        return json.loads(content[a:b + 1])
    except json.JSONDecodeError:
        return None


async def _call(msgs: list[dict]) -> dict | None:
    """POST to the chat API with recovery: retired model -> next model; JSON mode or reasoning flag refused ->
    retry without it. Remembers what worked. Any failure text is kept in last_error for the UI notice."""
    global _working_model, last_error
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
    groq = "groq.com" in settings.llm_base_url
    models = [_working_model] if _working_model else [settings.llm_model] + (
        [m for m in FALLBACK_MODELS if m != settings.llm_model] if groq else [])
    t0 = time.perf_counter()
    for model in models:
        for strict in (True, False):
            body = {"model": model, "temperature": 0, "messages": msgs}
            if strict:
                body["response_format"] = {"type": "json_object"}
                if "gpt-oss" in model:
                    body["reasoning_effort"] = "low"
            try:
                r = await _http().post(url, json=body, headers=headers)
            except Exception as e:
                last_error = f"network: {e.__class__.__name__}"
                log.warning("llm network error (%.0f ms): %s", (time.perf_counter() - t0) * 1000, e)
                return None
            if r.status_code in (401, 403):
                last_error = f"HTTP {r.status_code}: the LLM_API_KEY was rejected"
                log.warning("llm auth failed: %s", r.text[:300])
                return None
            if r.status_code == 429:
                last_error = "HTTP 429: rate limited"
                log.warning("llm rate limited: %s", r.text[:200])
                return None
            if r.status_code >= 400:
                txt = r.text[:300]
                last_error = f"HTTP {r.status_code} ({model}): {txt[:120]}"
                log.warning("llm %s with %s strict=%s: %s", r.status_code, model, strict, txt)
                low = txt.lower()
                if "model" in low and any(w in low for w in ("decommission", "not found", "does not exist", "not exist", "deprecated")):
                    break                      # try the next model
                continue                       # try again without json mode / reasoning flag
            try:
                content = r.json()["choices"][0]["message"]["content"]
            except Exception:
                content = ""
            data = _parse_json(content)
            if data is None:
                last_error = f"{model}: reply was not JSON"
                continue
            if _working_model != model:
                log.info("llm using model %s", model)
            _working_model, last_error = model, None
            return data
    return None


def _hhmm(v) -> str | None:
    if not isinstance(v, str):
        return None
    try:
        h, m = (int(x) for x in v.strip().split(":")[:2])
    except ValueError:
        return None
    return f"{h:02d}:{m:02d}" if 0 <= h < 24 and 0 <= m < 60 else None


def _date(v):
    from datetime import date
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _datetime(v):
    from datetime import datetime
    from .timeutil import IST
    try:
        d = datetime.fromisoformat(str(v)) if v else None
    except ValueError:
        return None
    return d.replace(tzinfo=IST) if d and d.tzinfo is None else d


def _num(v) -> float | None:
    if isinstance(v, str):
        try:
            v = float(v.replace(",", ""))
        except ValueError:
            return None
    return float(v) if isinstance(v, (int, float)) and v > 0 else None


def _mention(name: str | None, customers) -> Mention | None:
    if not name or not str(name).strip():
        return None
    ms = find_mentions(tokenize(str(name)), customers)
    known = [m for m in ms if m.known]
    if known:
        return known[0]
    return Mention(0, 0, [], 0.0, known=False, surface=str(name).strip())


def _safe_mention(chosen: str | None, heard: str | None, toks: list[str], customers) -> Mention | None:
    """The LLM may 'correct' a new name into an existing customer. Only accept its pick if our own
    matcher also hears that customer in the heard name (or the sentence); otherwise treat it as a new name."""
    m = _mention(chosen, customers)
    if m is None or not m.known:
        return m if heard is None else (_mention(heard, customers) or m)
    heard_ms = [x for x in find_mentions(tokenize(heard), customers) if x.known] if heard else \
        [x for x in find_mentions(toks, customers) if x.known]
    if any(set(x.candidates) & set(m.candidates) for x in heard_ms):
        return m
    if heard:
        return _mention(heard, customers)          # e.g. "Aniket" stays Aniket -> "naya khata?"
    return m if not toks else Mention(0, 0, [], 0.0, known=False, surface=str(chosen))


def to_clauses(text: str, raw: list[dict], customers) -> list[Clause]:
    toks = tokenize(text)
    spoken = {s.paise for s in find_numbers(toks)}
    today = today_ist()
    out: list[Clause] = []
    for item in raw[:5]:
        if not isinstance(item, dict):
            continue
        intent = str(item.get("intent") or "UNKNOWN").upper()
        if intent not in INTENTS:
            intent = "UNKNOWN"
        c = Clause(intent=intent, tokens=toks)
        if item.get("customer_ref") != "previous":
            c.mention = _safe_mention(item.get("customer"), item.get("heard_name"), toks, customers)
        amt = _num(item.get("amount_rupees"))
        c.amount = int(round(amt * 100)) if amt else None
        kind = str(item.get("kind") or "").upper()
        c.kind = kind if kind in ("CREDIT", "PAYMENT") else None
        c.kind_explicit = c.kind is not None
        days = item.get("days_ago")
        said_date = _date(item.get("date"))
        if said_date and said_date <= today:
            c.date, c.date_explicit = said_date, True
        elif isinstance(days, int) and 0 < days < 60:
            c.date, c.date_explicit = today - timedelta(days=days), True
        else:
            c.date = today
        c.txn_time = _hhmm(item.get("time"))
        c.reply = (item.get("reply") or "").strip()[:400] or None
        c.new_name = (item.get("new_name") or "").strip() or None
        c.name_hi = (item.get("name_hi") or "").strip() or None
        phone = "".join(ch for ch in str(item.get("phone") or "") if ch.isdigit())
        c.phone = phone if 8 <= len(phone) <= 13 else None
        c.settle_all = bool(item.get("settle_all"))
        if intent == "TXN":
            # kind None -> the dialogue asks "aapne diya ya aapko mila?" instead of guessing
            # trust the amount only if our own parser heard the same number
            c.confidence = 0.95 if c.amount in spoken else 0.6
        elif intent == "QUERY":
            q = str(item.get("query") or "BALANCE").upper()
            c.query = q if q in QUERIES else "BALANCE"
            per = item.get("period")
            if c.date_explicit and c.date != today:
                c.period, c.period_label = (c.date, c.date), None
            elif per == "yesterday":
                y = today - timedelta(days=1)
                c.period, c.period_label = (y, y), "yesterday"
            elif per == "this_week":
                c.period, c.period_label = (week_start(today), today), "this_week"
            elif per == "this_month":
                c.period, c.period_label = (month_start(today), today), "this_month"
            elif per == "today" or c.query.startswith("PERIOD"):
                c.period, c.period_label = (today, today), "today"
            c.top_n = 5 if c.query == "TOP_DEBTORS" else None
            if c.query == "LIST_ENTRIES" and not c.period:
                c.period, c.period_label = (today, today), "today"
        elif intent == "CORRECTION":
            new_amt = _num(item.get("new_amount_rupees")) or amt
            c.new_amount = int(round(new_amt * 100)) if new_amt else None
            c.old_amount = None
            c.new_mention = c.mention if (c.mention and not c.new_amount) else None
            c.mention = None if c.new_mention else c.mention
            c.new_kind = None
        elif intent == "SET_ALARM":
            c.alarm_at = _datetime(item.get("alarm_at"))
            c.alarm_text = (item.get("alarm_text") or "").strip() or text
        elif intent == "CLOSING_TIME":
            c.closing_time = c.txn_time
        elif intent == "RENAME_CUSTOMER":
            c.new_name = c.new_name and " ".join(w.capitalize() for w in c.new_name.split())
        out.append(c)
    return out
