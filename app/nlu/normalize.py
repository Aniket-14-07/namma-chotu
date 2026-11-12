"""Text normalisation: any STT output -> lowercase Latin tokens.

Clause separators (, . ? । |) become the token "|" so the parser can split
multi-transaction utterances such as "Ramesh ka 340 udhaar, kal 200 diya tha".
"""
from __future__ import annotations

import re

from .romanize import romanize

SEP = "|"

_RUPEE_RE = re.compile(r"₹\s*")
_RS_RE = re.compile(r"\brs\.?\s*(?=\d)", re.I)
_DIGIT_COMMA_RE = re.compile(r"(?<=\d),(?=\d)")
_SLASH_DASH_RE = re.compile(r"(\d)\s*/-")
_K_SUFFIX_RE = re.compile(r"(\d)\s*k\b", re.I)
_HYPHEN_RE = re.compile(r"(?<=[a-z])-(?=[a-z])")
_SEP_RE = re.compile(r"[,;?!|।]+|\.(?!\d)")
_JUNK_RE = re.compile(r"[^a-z0-9.\s|']")
_ORDINAL_RE = re.compile(r"(\d+)(st|nd|rd|th)\b")


def normalize(text: str) -> str:
    t = romanize(text or "")
    t = t.lower()
    t = _RUPEE_RE.sub(" rupaye ", t)
    t = _RS_RE.sub(" rupaye ", t)
    t = _SLASH_DASH_RE.sub(r"\1 rupaye ", t)
    t = _K_SUFFIX_RE.sub(r"\1 hazaar", t)
    # Indian/Western digit grouping: 1,250 / 1,00,000 -> join (repeat for chains)
    for _ in range(4):
        t = _DIGIT_COMMA_RE.sub("", t)
    t = _ORDINAL_RE.sub(r"\1", t)
    t = re.sub(r"'s\b", "", t)              # priya's -> priya
    t = _HYPHEN_RE.sub(" ", t)          # three-forty -> three forty
    t = t.replace("-", " ")
    t = _SEP_RE.sub(f" {SEP} ", t)
    t = _JUNK_RE.sub(" ", t)
    t = t.replace("'", "")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def tokenize(text: str) -> list[str]:
    toks = normalize(text).split()
    # collapse repeated separators / strip leading-trailing
    out: list[str] = []
    for tok in toks:
        if tok == SEP and (not out or out[-1] == SEP):
            continue
        out.append(tok)
    while out and out[-1] == SEP:
        out.pop()
    return out
