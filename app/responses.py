"""Replies in Hindi (Devanagari), Kannada (Kannada script) and English.

Native script matters: Timbre reads Latin-only text with English phonetics, so Hindi and
Kannada replies are written in their own scripts (names too, via transliteration).
Each reply is a list of parts; amounts/dates stay structured until render, so the screen
shows "₹1,240" while the voice says the amount in words (hi/en) or "1240 ರೂಪಾಯಿ" (kn).
No pressure or threat language anywhere (PS2 guardrail).

Kannada strings: written by the team's Kannada speaker should review (docs/LANGUAGE_REVIEW.md).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date

from .nlu.romanize import devanagari_to_kannada
from .numwords import fmt_inr, spoken_amount
from .timeutil import today_ist

SPEAK_WORDS = os.getenv("TTS_NUMBERS_AS_WORDS", "1") not in {"0", "false", "no"}
_MONTHS_EN = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


@dataclass
class Amt:
    paise: int


@dataclass
class Day:
    d: date


Part = str | Amt | Day

# --------------------------------------------------------------------------- phrasebook
T: dict[str, dict[str, str]] = {
    "greeting": {
        "hi": "नमस्ते! मैं नम्मा छोटू हूँ, एक AI सहायक। उधार या जमा बोलिए, मैं खाते में लिख दूँगा।",
        "kn": "ನಮಸ್ಕಾರ! ನಾನು ನಮ್ಮ ಛೋಟು, ಒಂದು AI ಸಹಾಯಕ. ಉದ್ರಿ ಅಥವಾ ಜಮಾ ಹೇಳಿ, ನಾನು ಖಾತೆಯಲ್ಲಿ ಬರೆಯುತ್ತೇನೆ.",
        "en": "Hello! I'm Namma Chotu, an AI assistant. Tell me any credit or payment and I'll record it.",
    },
    "disclosure": {"hi": "मैं एक AI सहायक हूँ। ", "kn": "ನಾನು ಒಂದು AI ಸಹಾಯಕ. ", "en": "I'm an AI assistant. "},
    "credit": {"hi": "उधार", "kn": "ಉದ್ರಿ", "en": "credit"},
    "payment": {"hi": "जमा", "kn": "ಜಮಾ", "en": "payment"},
    "stop": {"hi": "। ", "kn": ". ", "en": ". "},
    "corrected": {"hi": "ठीक किया। ", "kn": "ಸರಿ ಮಾಡಿದೆ. ", "en": "Corrected. "},
    "due": {"hi": "कुल बाकी {a}।", "kn": "ಒಟ್ಟು ಬಾಕಿ {a}.", "en": "Total due {a}."},
    "nothing_due": {"hi": "अब कुछ बाकी नहीं।", "kn": "ಈಗ ಏನೂ ಬಾಕಿ ಇಲ್ಲ.", "en": "Nothing due now."},
    "advance": {"hi": "{a} एडवांस है।", "kn": "{a} ಮುಂಗಡ ಇದೆ.", "en": "{a} in advance."},
    "ask_which": {"hi": "कौन से {first}? {opts}?", "kn": "ಯಾವ {first}? {opts}?", "en": "Which {first}? {opts}?"},
    "or": {"hi": " या ", "kn": " ಅಥವಾ ", "en": " or "},
    "ask_new_customer": {"hi": "{name} नाम का कोई ग्राहक नहीं है। नया खाता बनाऊँ?",
                         "kn": "{name} ಹೆಸರಿನ ಗ್ರಾಹಕರು ಇಲ್ಲ. ಹೊಸ ಖಾತೆ ತೆರೆಯಲೇ?",
                         "en": "There's no customer named {name}. Shall I open a new account?"},
    "ask_amount": {"hi": "{name} के कितने रुपये {kind}?", "kn": "{name} ಎಷ್ಟು ರೂಪಾಯಿ {kind}?",
                   "en": "How much {kind} for {name}?"},
    "ask_customer": {"hi": "{a} किसके नाम लिखूँ?", "kn": "{a} ಯಾರ ಹೆಸರಿಗೆ ಬರೆಯಲಿ?", "en": "Whose account should I put {a} in?"},
    "confirm_q": {"hi": "। सही है?", "kn": ". ಸರಿನಾ?", "en": ". Is that right?"},
    "overpay": {"hi": "{name} का बाकी सिर्फ़ {bal} है। {a} जमा करूँ? {adv} एडवांस रहेगा।",
                "kn": "{name} ಬಾಕಿ ಕೇವಲ {bal}. {a} ಜಮಾ ಮಾಡಲೇ? {adv} ಮುಂಗಡ ಉಳಿಯುತ್ತದೆ.",
                "en": "{name} only owes {bal}. Record {a}? {adv} will stay as advance."},
    "overpay_zero": {"hi": "{name} का कोई बाकी नहीं है। {a} एडवांस जमा करूँ?",
                     "kn": "{name} ಏನೂ ಬಾಕಿ ಇಲ್ಲ. {a} ಮುಂಗಡ ಜಮಾ ಮಾಡಲೇ?",
                     "en": "{name} owes nothing. Record {a} as advance?"},
    "cancelled": {"hi": "ठीक है, कुछ नहीं लिखा।", "kn": "ಸರಿ, ಏನೂ ಬರೆದಿಲ್ಲ.", "en": "Okay, nothing recorded."},
    "nothing_to_undo": {"hi": "हटाने के लिए कोई ताज़ा एंट्री नहीं है।", "kn": "ತೆಗೆಯಲು ಯಾವುದೇ ಹೊಸ ಎಂಟ್ರಿ ಇಲ್ಲ.",
                        "en": "There's no recent entry to remove."},
    "nothing_to_correct": {"hi": "ठीक करने के लिए कोई ताज़ा एंट्री नहीं है। पूरी एंट्री दोबारा बोलिए।",
                           "kn": "ಸರಿಪಡಿಸಲು ಯಾವುದೇ ಹೊಸ ಎಂಟ್ರಿ ಇಲ್ಲ. ಪೂರ್ತಿ ಎಂಟ್ರಿ ಮತ್ತೆ ಹೇಳಿ.",
                           "en": "There's no recent entry to correct. Please say the full entry again."},
    "duplicate": {"hi": "ये एंट्री अभी लिख चुका हूँ।", "kn": "ಈ ಎಂಟ್ರಿ ಈಗಾಗಲೇ ಬರೆದಿದ್ದೇನೆ.",
                  "en": "I've already recorded that entry."},
    "not_understood": {"hi": "माफ़ कीजिए, समझ नहीं आया। ऐसे बोलिए: रमेश का तीन सौ चालीस उधार।",
                       "kn": "ಕ್ಷಮಿಸಿ, ಅರ್ಥ ಆಗಲಿಲ್ಲ. ಹೀಗೆ ಹೇಳಿ: ರಮೇಶ್ ಮುನ್ನೂರ ನಲವತ್ತು ಉದ್ರಿ.",
                       "en": "Sorry, I didn't get that. Try: Ramesh, 340 credit."},
    "greeting_reply": {"hi": "नमस्ते! बताइए, किसका हिसाब लिखूँ?", "kn": "ನಮಸ್ಕಾರ! ಯಾರ ಲೆಕ್ಕ ಬರೆಯಲಿ?",
                       "en": "Hello! Whose account shall I update?"},
    "yes_no_pending": {"hi": "जी, बताइए?", "kn": "ಹೇಳಿ?", "en": "Yes, go ahead?"},
    "unknown_customer": {"hi": "{name} नाम का कोई ग्राहक नहीं मिला।", "kn": "{name} ಹೆಸರಿನ ಗ್ರಾಹಕರು ಸಿಗಲಿಲ್ಲ.",
                         "en": "I couldn't find a customer named {name}."},
    "future": {"hi": "ठीक है, जब {name} पैसे देंगे तब बताइए। अभी कुछ नहीं लिखा।",
               "kn": "ಸರಿ, {name} ಹಣ ಕೊಟ್ಟಾಗ ಹೇಳಿ. ಈಗ ಏನೂ ಬರೆದಿಲ್ಲ.",
               "en": "Okay, tell me when {name} actually pays. Nothing recorded yet."},
    "someone": {"hi": "ग्राहक", "kn": "ಗ್ರಾಹಕರು", "en": "the customer"},
    "negation": {"hi": "ठीक है, कुछ नहीं लिखा।", "kn": "ಸರಿ, ಏನೂ ಬರೆದಿಲ್ಲ.", "en": "Okay, nothing recorded."},
    "reminder_no_optin": {"hi": "{name} ने याद-संदेश के लिए हाँ नहीं कहा है, इसलिए मैं नहीं भेजूँगा।",
                          "kn": "{name} ಅವರು ನೆನಪಿನ ಸಂದೇಶಕ್ಕೆ ಒಪ್ಪಿಗೆ ಕೊಟ್ಟಿಲ್ಲ, ಹಾಗಾಗಿ ನಾನು ಕಳಿಸುವುದಿಲ್ಲ.",
                          "en": "{name} hasn't agreed to reminders, so I won't send one."},
    "reminder_ready": {"hi": "{name} के लिए एक विनम्र याद-संदेश तैयार है। भेजने का बटन स्क्रीन पर है।",
                       "kn": "{name} ಅವರಿಗೆ ಒಂದು ವಿನಯದ ನೆನಪಿನ ಸಂದೇಶ ಸಿದ್ಧ. ಕಳಿಸುವ ಬಟನ್ ಸ್ಕ್ರೀನ್ ಮೇಲೆ ಇದೆ.",
                       "en": "A polite reminder for {name} is ready. The send button is on screen."},
    "reminder_zero": {"hi": "{name} का कोई बाकी नहीं है, याद-संदेश की ज़रूरत नहीं।",
                      "kn": "{name} ಅವರದು ಏನೂ ಬಾಕಿ ಇಲ್ಲ, ನೆನಪಿನ ಸಂದೇಶ ಬೇಕಿಲ್ಲ.",
                      "en": "{name} owes nothing, no reminder needed."},
    "refuse_lending": {"hi": "माफ़ कीजिए, मैं ब्याज या लोन का हिसाब नहीं रखता। सिर्फ़ सामान का उधार और जमा लिखता हूँ।",
                       "kn": "ಕ್ಷಮಿಸಿ, ನಾನು ಬಡ್ಡಿ ಅಥವಾ ಸಾಲದ ಲೆಕ್ಕ ಇಡುವುದಿಲ್ಲ. ಸಾಮಾನಿನ ಉದ್ರಿ ಮತ್ತು ಜಮಾ ಮಾತ್ರ ಬರೆಯುತ್ತೇನೆ.",
                       "en": "Sorry, I don't handle interest or loans. I only record goods on credit and payments."},
    "refuse_pressure": {"hi": "माफ़ कीजिए, मैं धमकी या दबाव वाला संदेश नहीं भेजता। चाहें तो एक विनम्र याद-संदेश बना सकता हूँ।",
                        "kn": "ಕ್ಷಮಿಸಿ, ನಾನು ಬೆದರಿಕೆ ಅಥವಾ ಒತ್ತಡದ ಸಂದೇಶ ಕಳಿಸುವುದಿಲ್ಲ. ಬೇಕಾದರೆ ವಿನಯದ ನೆನಪಿನ ಸಂದೇಶ ಮಾಡಬಹುದು.",
                        "en": "Sorry, I don't send threatening or pressuring messages. I can prepare a polite reminder instead."},
    "kept_pending_dropped": {"hi": "पिछला सवाल छोड़ दिया। ", "kn": "ಹಿಂದಿನ ಪ್ರಶ್ನೆ ಬಿಟ್ಟೆ. ", "en": "Dropped the earlier question. "},
    "new_customer_created": {"hi": "नया खाता बना: {name}। ", "kn": "ಹೊಸ ಖಾತೆ: {name}. ", "en": "New account: {name}. "},
    "undo_done": {"hi": "{name} की {a} {kind} वाली एंट्री हटा दी। ", "kn": "{name} ಅವರ {a} {kind} ಎಂಟ್ರಿ ತೆಗೆದೆ. ",
                  "en": "Removed {name}'s {a} {kind} entry. "},
    "balance_pos": {"hi": "{name} का कुल बाकी {a} है।", "kn": "{name} ಒಟ್ಟು ಬಾಕಿ {a}.", "en": "{name} owes {a} in total."},
    "balance_zero": {"hi": "{name} का कोई बाकी नहीं है।", "kn": "{name} ಏನೂ ಬಾಕಿ ಇಲ್ಲ.", "en": "{name} owes nothing."},
    "balance_neg": {"hi": "{name} का {a} एडवांस जमा है।", "kn": "{name} ಅವರದು {a} ಮುಂಗಡ ಇದೆ.", "en": "{name} has {a} in advance."},
    "last_payment": {"hi": "{name} ने आख़िरी बार {d} {a} दिए थे।", "kn": "{name} ಕೊನೆಯದಾಗಿ {d} {a} ಕೊಟ್ಟಿದ್ದಾರೆ.",
                     "en": "{name} last paid {a} on {d}."},
    "last_credit": {"hi": "{name} का आख़िरी उधार {d} {a} था।", "kn": "{name} ಕೊನೆಯ ಉದ್ರಿ {d} {a}.",
                    "en": "{name} last took credit of {a} on {d}."},
    "no_entries": {"hi": "{name} की कोई एंट्री नहीं है।", "kn": "{name} ಅವರ ಯಾವುದೇ ಎಂಟ್ರಿ ಇಲ್ಲ.", "en": "No entries for {name}."},
    "period_credit": {"hi": "{p} {a} उधार गया, {n} एंट्री।", "kn": "{p} {a} ಉದ್ರಿ ಹೋಗಿದೆ, {n} ಎಂಟ್ರಿ.",
                      "en": "{p}: {a} given on credit, {n} entries."},
    "period_payment": {"hi": "{p} {a} जमा हुए, {n} एंट्री।", "kn": "{p} {a} ಜಮಾ ಆಗಿದೆ, {n} ಎಂಟ್ರಿ.",
                       "en": "{p}: {a} received, {n} entries."},
    "period_none": {"hi": "{p} कोई {kind} एंट्री नहीं हुई।", "kn": "{p} ಯಾವುದೇ {kind} ಎಂಟ್ರಿ ಇಲ್ಲ.",
                    "en": "{p}: no {kind} entries."},
    "period_summary": {"hi": "{p} {a} उधार गया और {b} जमा हुए।", "kn": "{p} {a} ಉದ್ರಿ ಹೋಗಿದೆ, {b} ಜಮಾ ಆಗಿದೆ.",
                       "en": "{p}: {a} on credit, {b} received."},
    "outstanding": {"hi": "कुल {a} बाज़ार में बाकी है, {n} ग्राहकों पर।", "kn": "ಒಟ್ಟು {a} ಮಾರ್ಕೆಟ್‌ನಲ್ಲಿ ಬಾಕಿ ಇದೆ, {n} ಗ್ರಾಹಕರ ಮೇಲೆ.",
                    "en": "Total {a} is pending with {n} customers."},
    "top_none": {"hi": "किसी पर उधार बाकी नहीं है।", "kn": "ಯಾರ ಮೇಲೂ ಉದ್ರಿ ಬಾಕಿ ಇಲ್ಲ.", "en": "Nobody owes anything."},
    "top_one": {"hi": "सबसे ज़्यादा उधार {name} पर है, {a}।", "kn": "ಅತಿ ಹೆಚ್ಚು ಉದ್ರಿ {name} ಮೇಲೆ, {a}.",
                "en": "{name} owes the most, {a}."},
    "top_many": {"hi": "सबसे ज़्यादा उधार: ", "kn": "ಅತಿ ಹೆಚ್ಚು ಉದ್ರಿ: ", "en": "Top dues: "},
    "customer_count": {"hi": "आपके {n} ग्राहक हैं, जिनमें से {m} पर उधार बाकी है।",
                       "kn": "ನಿಮಗೆ {n} ಗ್ರಾಹಕರು ಇದ್ದಾರೆ, ಅವರಲ್ಲಿ {m} ಜನರ ಮೇಲೆ ಉದ್ರಿ ಬಾಕಿ ಇದೆ.",
                       "en": "You have {n} customers; {m} of them owe money."},
}

_DAYS_REL = {"hi": {0: "आज", 1: "कल", 2: "परसों"}, "kn": {0: "ಇವತ್ತು", 1: "ನಿನ್ನೆ", 2: "ಮೊನ್ನೆ"},
             "en": {0: "today", 1: "yesterday", 2: "day before yesterday"}}
_PERIOD = {
    "hi": {"today": "आज", "yesterday": "कल", "day_before": "परसों", "this_week": "इस हफ़्ते",
           "last_week": "पिछले हफ़्ते", "this_month": "इस महीने", "last_month": "पिछले महीने"},
    "kn": {"today": "ಇವತ್ತು", "yesterday": "ನಿನ್ನೆ", "day_before": "ಮೊನ್ನೆ", "this_week": "ಈ ವಾರ",
           "last_week": "ಹೋದ ವಾರ", "this_month": "ಈ ತಿಂಗಳು", "last_month": "ಹೋದ ತಿಂಗಳು"},
    "en": {"today": "Today", "yesterday": "Yesterday", "day_before": "Day before yesterday", "this_week": "This week",
           "last_week": "Last week", "this_month": "This month", "last_month": "Last month"},
}


def L(lang: str) -> str:
    return lang if lang in ("hi", "kn", "en") else "en"


def t(key: str, lang: str) -> str:
    return T[key][L(lang)]


# --------------------------------------------------------------------------- rendering
def _day_text(d: date, lang: str, speak: bool) -> str:
    rel = _DAYS_REL[L(lang)].get((today_ist() - d).days)
    if rel:
        return rel
    return f"{d.day} {_MONTHS_EN[d.month - 1]}" + (f" {d.year}" if speak else "")


def _speak_amount(paise: int, lang: str) -> str:
    if L(lang) == "kn":
        rupees, p = divmod(abs(paise), 100)
        return f"{rupees} ರೂಪಾಯಿ" + (f" {p} ಪೈಸೆ" if p else "")
    return spoken_amount(paise, L(lang)) if SPEAK_WORDS else fmt_inr(paise)


def render(parts: list[Part], lang: str) -> tuple[str, str]:
    """-> (display_text, speak_text)"""
    disp, speak = [], []
    for p in parts:
        if isinstance(p, Amt):
            disp.append(fmt_inr(p.paise))
            speak.append(_speak_amount(p.paise, lang))
        elif isinstance(p, Day):
            disp.append(_day_text(p.d, lang, False))
            speak.append(_day_text(p.d, lang, True))
        else:
            disp.append(p)
            speak.append(p)
    return "".join(disp), "".join(speak)


def fill(key: str, lang: str, **kw) -> list[Part]:
    """Template -> parts; Amt/Day values stay structured."""
    tpl = t(key, lang)
    parts: list[Part] = []
    i = 0
    while i < len(tpl):
        j = tpl.find("{", i)
        if j < 0:
            parts.append(tpl[i:])
            break
        k = tpl.index("}", j)
        if j > i:
            parts.append(tpl[i:j])
        v = kw[tpl[j + 1:k]]
        parts.append(v if isinstance(v, (Amt, Day)) else str(v))
        i = k + 1
    return parts


def kind_word(kind: str | None, lang: str) -> str:
    return t("payment" if kind == "PAYMENT" else "credit", lang)


def name_for(cust, lang: str) -> str:
    if cust is None:
        return ""
    hi = getattr(cust, "name_hi", None)
    if L(lang) == "hi" and hi:
        return hi
    if L(lang) == "kn" and hi:
        return devanagari_to_kannada(hi)
    return cust.name


# --------------------------------------------------------------------------- builders
def greeting(lang: str) -> list[Part]:
    return [t("greeting", lang)]


def disclosure(lang: str) -> list[Part]:
    return [t("disclosure", lang)]


def balance_tail(bal: int, lang: str) -> list[Part]:
    if bal > 0:
        return fill("due", lang, a=Amt(bal))
    if bal == 0:
        return [t("nothing_due", lang)]
    return fill("advance", lang, a=Amt(-bal))


def txn_group(cust, txns: list, bal: int, lang: str, corrected: bool = False) -> list[Part]:
    """'रमेश कुमार: ₹340 उधार, कल ₹200 जमा। कुल बाकी ₹1,240।'"""
    parts: list[Part] = [t("corrected", lang)] if corrected else []
    parts += [name_for(cust, lang), ": "]
    for i, tx in enumerate(txns):
        if i:
            parts.append(", ")
        d = date.fromisoformat(tx.txn_date)
        if d != today_ist():
            parts += [Day(d), " "]
        parts += [Amt(tx.amount_paise), " ", kind_word(tx.kind, lang)]
    parts.append(t("stop", lang))
    return parts + balance_tail(bal, lang)


def ask_which(first: str, options: list, lang: str) -> list[Part]:
    opts = t("or", lang).join(name_for(o, lang) for o in options[:3])
    return fill("ask_which", lang, first=first, opts=opts)


def ask_new_customer(name: str, lang: str) -> list[Part]:
    return fill("ask_new_customer", lang, name=name)


def ask_amount(cust_name: str, kind: str | None, lang: str) -> list[Part]:
    return fill("ask_amount", lang, name=cust_name, kind=kind_word(kind, lang))


def ask_customer(amount: int, lang: str) -> list[Part]:
    return fill("ask_customer", lang, a=Amt(amount))


def ask_confirm(cust_name: str, amount: int, kind: str, d: date, lang: str) -> list[Part]:
    parts: list[Part] = [cust_name, ", "]
    if d != today_ist():
        parts += [Day(d), " "]
    return parts + [Amt(amount), " ", kind_word(kind, lang), t("confirm_q", lang)]


def ask_overpay(cust_name: str, bal: int, amount: int, lang: str) -> list[Part]:
    if bal <= 0:
        return fill("overpay_zero", lang, name=cust_name, a=Amt(amount))
    return fill("overpay", lang, name=cust_name, bal=Amt(bal), a=Amt(amount), adv=Amt(amount - bal))


def simple(key: str, lang: str, **kw) -> list[Part]:
    return fill(key, lang, **kw)


def undo_done(cust, txn, bal: int, lang: str) -> list[Part]:
    return fill("undo_done", lang, name=name_for(cust, lang), a=Amt(txn.amount_paise),
                kind=kind_word(txn.kind, lang)) + balance_tail(bal, lang)


def period_word(label: str | None, start: date | None, lang: str) -> Part:
    table = _PERIOD[L(lang)]
    if label in table:
        return table[label]
    return Day(start) if start else table["today"]


def balance(cust, bal: int, lang: str) -> list[Part]:
    n = name_for(cust, lang)
    if bal > 0:
        return fill("balance_pos", lang, name=n, a=Amt(bal))
    if bal == 0:
        return fill("balance_zero", lang, name=n)
    return fill("balance_neg", lang, name=n, a=Amt(-bal))


def last_txn(cust, txn, kind: str | None, lang: str) -> list[Part]:
    n = name_for(cust, lang)
    if txn is None:
        return fill("no_entries", lang, name=n)
    key = "last_payment" if txn.kind == "PAYMENT" else "last_credit"
    return fill(key, lang, name=n, d=Day(date.fromisoformat(txn.txn_date)), a=Amt(txn.amount_paise))


def period_sum(kind: str, label, start, total: int, count: int, lang: str) -> list[Part]:
    p = period_word(label, start, lang)
    if count == 0:
        return fill("period_none", lang, p=p, kind=kind_word(kind, lang))
    key = "period_payment" if kind == "PAYMENT" else "period_credit"
    return fill(key, lang, p=p, a=Amt(total), n=count)


def period_summary(label, start, credit: int, paid: int, lang: str) -> list[Part]:
    return fill("period_summary", lang, p=period_word(label, start, lang), a=Amt(credit), b=Amt(paid))


def total_outstanding(total: int, n: int, lang: str) -> list[Part]:
    return fill("outstanding", lang, a=Amt(total), n=n)


def top_debtors(items: list, lang: str) -> list[Part]:
    if not items:
        return [t("top_none", lang)]
    if len(items) == 1:
        c, b = items[0]
        return fill("top_one", lang, name=name_for(c, lang), a=Amt(b))
    parts: list[Part] = [t("top_many", lang)]
    for i, (c, b) in enumerate(items):
        if i:
            parts.append(", ")
        parts += [name_for(c, lang), " ", Amt(b)]
    parts.append(t("stop", lang).strip())
    return parts


def customer_count(n: int, owing: int, lang: str) -> list[Part]:
    return fill("customer_count", lang, n=n, m=owing)


def reminder_message(cust, bal: int, shop: str = "Namma Chotu Kirana") -> str:
    """Text the shopkeeper may choose to send (opt-in customers only). Polite, no pressure."""
    hi_name = cust.name_hi or cust.name
    return (f"नमस्ते {hi_name} जी, आपके खाते में {fmt_inr(bal)} बाकी है। जब सुविधा हो, दे दीजिएगा। "
            f"धन्यवाद! — {shop}\n(Hello {cust.name} ji, {fmt_inr(bal)} is pending in your account. "
            f"Please pay whenever convenient. Thank you!)")
