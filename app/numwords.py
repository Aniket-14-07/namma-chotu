"""Amounts -> display strings and -> spoken words (Hindi / English).

Timbre's text normaliser reads "₹1,240" itself, but spelling amounts as words is
the zero-risk option for a judged demo (TTS_NUMBERS_AS_WORDS=1, default on).
"""
from __future__ import annotations

HI_1_99 = (
    "शून्य एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस "
    "बीस इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस इकतीस बत्तीस तैंतीस चौंतीस "
    "पैंतीस छत्तीस सैंतीस अड़तीस उनतालीस चालीस इकतालीस बयालीस तैंतालीस चवालीस पैंतालीस छियालीस "
    "सैंतालीस अड़तालीस उनचास पचास इक्यावन बावन तिरेपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ साठ "
    "इकसठ बासठ तिरेसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर सत्तर इकहत्तर बहत्तर तिहत्तर चौहत्तर "
    "पचहत्तर छिहत्तर सतहत्तर अठहत्तर उन्यासी अस्सी इक्यासी बयासी तिरासी चौरासी पचासी छियासी "
    "सत्तासी अट्ठासी नवासी नब्बे इक्यानवे बानवे तिरानवे चौरानवे पचानवे छियानवे सत्तानवे अट्ठानवे निन्यानवे"
).split()
assert len(HI_1_99) == 100

_EN_U = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
         "sixteen seventeen eighteen nineteen").split()
_EN_T = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _en_99(n: int) -> str:
    if n < 20:
        return _EN_U[n]
    t, u = divmod(n, 10)
    return _EN_T[t] + ("" if u == 0 else " " + _EN_U[u])


def _indian_parts(n: int) -> list[tuple[int, str]]:
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    hundred, rest = divmod(n, 100)
    return [(crore, "crore"), (lakh, "lakh"), (thousand, "thousand"), (hundred, "hundred"), (rest, "")]


def words_hi(n: int) -> str:
    if n == 0:
        return HI_1_99[0]
    names = {"crore": "करोड़", "lakh": "लाख", "thousand": "हज़ार", "hundred": "सौ", "": ""}
    out = []
    for v, unit in _indian_parts(n):
        if v:
            out.append(HI_1_99[v] if v < 100 else words_hi(v))
            if names[unit]:
                out.append(names[unit])
    return " ".join(out)


def words_en(n: int) -> str:
    if n == 0:
        return "zero"
    out = []
    for v, unit in _indian_parts(n):
        if v:
            out.append(_en_99(v) if v < 100 else words_en(v))
            if unit:
                out.append(unit)
    return " ".join(out)


def fmt_inr(paise: int) -> str:
    """₹1,24,050 style (Indian grouping). Shows paise only when non-zero."""
    neg = paise < 0
    rupees, p = divmod(abs(paise), 100)
    s = str(rupees)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups) + "," + tail
    out = f"₹{s}" + (f".{p:02d}" if p else "")
    return ("-" if neg else "") + out


def spoken_amount(paise: int, lang: str) -> str:
    rupees, p = divmod(abs(paise), 100)
    if lang == "hi":
        s = f"{words_hi(rupees)} रुपये"
        if p:
            s += f" {words_hi(p)} पैसे"
        return s
    s = f"{words_en(rupees)} rupees"
    if p:
        s += f" and {words_en(p)} paise"
    return s
