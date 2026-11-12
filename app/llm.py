"""Optional LLM fallback for utterances the rule parser can't read (e.g. Kannada, Tamil).

The LLM only *extracts structure*. It never computes balances or answers questions about
money; the ledger engine does. An amount the LLM returns is trusted only if the same
number is also found in the transcript by our own number parser; otherwise the
dialogue asks for confirmation before writing.
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta

import httpx

from .config import settings
from .nlu.names import Mention, find_mentions
from .nlu.normalize import tokenize
from .nlu.numbers import find_numbers
from .nlu.parser import Clause
from .timeutil import today_ist

log = logging.getLogger("llm")

SYSTEM = """You convert a kirana shopkeeper's spoken ledger command (any Indian language, code-mixed) into JSON.
Return ONLY: {"clauses":[{"intent":"TXN|QUERY|CORRECTION|UNDO|YES|NO|UNKNOWN",
 "customer": string|null, "kind":"CREDIT|PAYMENT"|null, "amount_rupees": number|null,
 "days_ago": integer|null, "query":"BALANCE|PERIOD_CREDIT|PERIOD_PAYMENTS|PERIOD_SUMMARY|TOTAL_OUTSTANDING|TOP_DEBTORS|CUSTOMER_COUNT|LAST_PAYMENT"|null,
 "period":"today|yesterday|this_week|this_month"|null}]}
CREDIT = customer took goods on credit (udhaar, owes more). PAYMENT = customer paid money back.
Write customer names in Latin letters. Never invent amounts; use null if no amount was spoken.
A future promise ("will pay tomorrow") is intent UNKNOWN. Multiple transactions -> multiple clauses."""


async def extract(text: str, customers) -> list[Clause] | None:
    if not settings.llm_enabled:
        return None
    names = ", ".join(c.name for c in customers)[:1500]
    body = {
        "model": settings.llm_model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Known customers: {names}\nUtterance: {text}"},
        ],
    }
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_s) as client:
            r = await client.post(url, json=body, headers={"Authorization": f"Bearer {settings.llm_api_key}"})
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
    except Exception as e:  # network, timeout, bad JSON: just fall back to "didn't understand"
        log.warning("llm fallback failed: %s", e)
        return None
    return _to_clauses(text, data.get("clauses") or [], customers)


def _to_clauses(text: str, raw: list[dict], customers) -> list[Clause]:
    spoken = {s.paise for s in find_numbers(tokenize(text))}
    today = today_ist()
    out: list[Clause] = []
    for item in raw[:4]:
        intent = (item.get("intent") or "UNKNOWN").upper()
        c = Clause(intent=intent, tokens=tokenize(text))
        name = item.get("customer")
        if name:
            ms = find_mentions(tokenize(name), customers)
            c.mention = ms[0] if ms else Mention(0, 0, [], 0.0, known=False, surface=name)
        amt = item.get("amount_rupees")
        if isinstance(amt, (int, float)) and amt > 0:
            c.amount = int(round(amt * 100))
        c.kind = item.get("kind") if item.get("kind") in ("CREDIT", "PAYMENT") else None
        c.kind_explicit = c.kind is not None
        days = item.get("days_ago")
        c.date = today - timedelta(days=int(days)) if isinstance(days, int) and 0 <= days < 60 else today
        if intent == "TXN":
            # trust the amount only if our own parser heard the same number
            c.confidence = 0.9 if c.amount in spoken else 0.6
            c.kind = c.kind or "CREDIT"
        if intent == "QUERY":
            c.query = item.get("query") or "BALANCE"
            per = item.get("period")
            if per == "yesterday":
                c.period, c.period_label = (today - timedelta(days=1),) * 2, "yesterday"
            elif per == "this_week":
                from .timeutil import week_start
                c.period, c.period_label = (week_start(today), today), "this_week"
            elif per == "this_month":
                from .timeutil import month_start
                c.period, c.period_label = (month_start(today), today), "this_month"
            elif per == "today":
                c.period, c.period_label = (today, today), "today"
            c.top_n = 5 if c.query == "TOP_DEBTORS" else None
        if intent == "CORRECTION":
            c.new_amount = c.amount
            c.new_mention = c.mention
            c.mention = None
        out.append(c)
    return out
