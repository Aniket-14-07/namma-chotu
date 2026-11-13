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
           "GREETING", "FUTURE", "REMINDER", "UNKNOWN"}
QUERIES = {"BALANCE", "LAST_PAYMENT", "LAST_CREDIT", "PERIOD_CREDIT", "PERIOD_PAYMENTS", "PERIOD_SUMMARY",
           "TOTAL_OUTSTANDING", "TOP_DEBTORS", "CUSTOMER_COUNT"}

SYSTEM = """You are the language-understanding module of "Namma Chotu", a voice khata (credit ledger) for Indian kirana shops.
The shopkeeper speaks Hindi, Kannada, English or a mix, in any script; speech-to-text may misspell words and names.
Convert the LATEST utterance into JSON commands. Use the conversation context to resolve "he/isko/usko/avrige",
answers to the assistant's last question, and follow-ups like "aur 200".

Return ONLY this JSON:
{"commands":[{
 "intent": "TXN|QUERY|CORRECTION|UNDO|YES|NO|ADD_CUSTOMER|RENAME_CUSTOMER|GREETING|FUTURE|REMINDER|UNKNOWN",
 "customer": string|null,        // customer name in Latin letters as spoken; null if not said
 "customer_ref": "named|previous|none",  // previous = pronoun / the customer just discussed
 "kind": "CREDIT|PAYMENT"|null,
 "amount_rupees": number|null,   // never invent; null if no amount was said
 "days_ago": integer|null,       // kal (past) = 1, parso = 2, ninne = 1; null = today
 "query": "BALANCE|LAST_PAYMENT|LAST_CREDIT|PERIOD_CREDIT|PERIOD_PAYMENTS|PERIOD_SUMMARY|TOTAL_OUTSTANDING|TOP_DEBTORS|CUSTOMER_COUNT"|null,
 "period": "today|yesterday|this_week|this_month"|null,
 "new_name": string|null,        // ADD_CUSTOMER / RENAME_CUSTOMER: the correct full name, Latin letters, Title Case
 "name_hi": string|null,         // the same customer name written in Devanagari (for natural Hindi speech)
 "phone": string|null,           // digits only, if a phone number was said for ADD_CUSTOMER
 "new_amount_rupees": number|null // CORRECTION: the corrected amount
}]}

Meaning of kind (from the SHOP's point of view; balance = what the customer owes the shop):
- CREDIT: customer took goods on credit / udhaar / baaki / "likh do" / ಉದ್ರಿ / "khate mein daalo",
  OR the shop lent cash / loan / "paise diye" TO the customer ("Ramesh ko 500 diye", "loan diya").
- PAYMENT: customer paid / jama / wapas kiya / "Ramesh ne 500 diye" / ಕೊಟ್ಟರು / ಜಮಾ / "received" / advance deposited by customer.
- Hindi "ko diya" = shop gave -> CREDIT. "ne diya" = customer gave -> PAYMENT. Kannada "avrige kotte" = CREDIT, "avru kottru" = PAYMENT.
- If the direction is truly unclear, use CREDIT for "udhaar"-like words; otherwise CREDIT and the app will confirm.

Other rules:
- "Kitna baaki hai / eshtu baaki / how much does X owe" = QUERY BALANCE. "Aaj ka hisaab / sales / ವ್ಯಾಪಾರ / summary" = QUERY PERIOD_SUMMARY (period today unless said).
  "Total kitna udhaar hai bazaar mein" = TOTAL_OUTSTANDING. "Sabse zyada kiska baaki" = TOP_DEBTORS.
- "Nahi, 430 tha / galat, 340 nahi 430" = CORRECTION with new_amount_rupees. "Hata do / cancel / undo / ತೆಗೆ" = UNDO.
- "Naya customer / naya khata / add karo <name>" = ADD_CUSTOMER with new_name.
- "<X> ka naam <Y> karo / spelling galat hai, <Y> likho / naam badlo" = RENAME_CUSTOMER: customer = X (or previous), new_name = Y.
- When the assistant just asked a yes/no question: haan/ha/ಹೌದು/sari/ok/yes = YES; nahi/ಇಲ್ಲ/beda/no = NO.
- When the assistant just asked for a name or amount, a bare name or number answers it (TXN with only that field).
- When the assistant asked "open a new account for X?" and the shopkeeper says a different/corrected name, return ADD_CUSTOMER with new_name = corrected name.
- Future promise ("kal dega", "will pay tomorrow") = FUTURE. Hello/namaste = GREETING. Anything else = UNKNOWN.
- Match spoken names to the known customer list when they clearly refer to one (fix STT misspellings, e.g. "Rames Kumaar" -> "Ramesh Kumar").
- Several actions in one sentence -> several commands, in order."""


def _ctx_lines(history: list[tuple[str, str]], last_customer: str | None, pending: str | None) -> str:
    lines = []
    for role, text in history[-6:]:
        lines.append(f"{'Shopkeeper' if role == 'user' else 'Assistant'}: {text}")
    out = "Conversation so far:\n" + ("\n".join(lines) if lines else "(none)")
    if last_customer:
        out += f"\nCustomer just discussed: {last_customer}"
    if pending:
        out += f"\nThe assistant is waiting for an answer to: {pending}"
    return out


async def extract(text: str, customers, *, history: list[tuple[str, str]] | None = None,
                  last_customer: str | None = None, pending: str | None = None) -> list[Clause] | None:
    if not settings.llm_enabled:
        return None
    names = ", ".join(c.name for c in customers)[:3000]
    user = (f"Known customers: {names or '(none yet)'}\n{_ctx_lines(history or [], last_customer, pending)}\n\n"
            f"LATEST utterance: {text}")
    body = {
        "model": settings.llm_model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
    }
    if "gpt-oss" in settings.llm_model:
        body["reasoning_effort"] = "low"     # Groq gpt-oss: keep the thinking short, this is a voice turn
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_s) as client:
            r = await client.post(url, json=body, headers={"Authorization": f"Bearer {settings.llm_api_key}"})
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
    except Exception as e:  # network, timeout, bad JSON: the rule parser takes over
        log.warning("llm failed (%.0f ms): %s", (time.perf_counter() - t0) * 1000, e)
        return None
    log.info("llm %.0f ms: %s", (time.perf_counter() - t0) * 1000, json.dumps(data, ensure_ascii=False)[:400])
    raw = data.get("commands") or data.get("clauses") or []
    if not isinstance(raw, list):
        return None
    return to_clauses(text, raw, customers)


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
            c.mention = _mention(item.get("customer"), customers)
        amt = _num(item.get("amount_rupees"))
        c.amount = int(round(amt * 100)) if amt else None
        kind = str(item.get("kind") or "").upper()
        c.kind = kind if kind in ("CREDIT", "PAYMENT") else None
        c.kind_explicit = c.kind is not None
        days = item.get("days_ago")
        if isinstance(days, int) and 0 < days < 60:
            c.date, c.date_explicit = today - timedelta(days=days), True
        else:
            c.date = today
        c.new_name = (item.get("new_name") or "").strip() or None
        c.name_hi = (item.get("name_hi") or "").strip() or None
        phone = "".join(ch for ch in str(item.get("phone") or "") if ch.isdigit())
        c.phone = phone if 8 <= len(phone) <= 13 else None
        if intent == "TXN":
            c.kind = c.kind or "CREDIT"
            # trust the amount only if our own parser heard the same number
            c.confidence = 0.95 if c.amount in spoken else 0.6
        elif intent == "QUERY":
            q = str(item.get("query") or "BALANCE").upper()
            c.query = q if q in QUERIES else "BALANCE"
            per = item.get("period")
            if per == "yesterday":
                y = today - timedelta(days=1)
                c.period, c.period_label = (y, y), "yesterday"
            elif per == "this_week":
                c.period, c.period_label = (week_start(today), today), "this_week"
            elif per == "this_month":
                c.period, c.period_label = (month_start(today), today), "this_month"
            elif per == "today" or c.query.startswith("PERIOD"):
                c.period, c.period_label = (today, today), "today"
            c.top_n = 5 if c.query == "TOP_DEBTORS" else None
        elif intent == "CORRECTION":
            new_amt = _num(item.get("new_amount_rupees")) or amt
            c.new_amount = int(round(new_amt * 100)) if new_amt else None
            c.old_amount = None
            c.new_mention = c.mention if (c.mention and not c.new_amount) else None
            c.mention = None if c.new_mention else c.mention
            c.new_kind = None
        elif intent == "RENAME_CUSTOMER":
            c.new_name = c.new_name and " ".join(w.capitalize() for w in c.new_name.split())
        out.append(c)
    return out
