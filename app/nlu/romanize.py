"""Devanagari -> Latin romanisation and phonetic keys.

Prisma v3.0 in `transcribe` mode returns Hindi in Devanagari with English words
in Latin and numbers as digits ("रमेश का 340 उधार"). Everything downstream works
on one canonical form: lowercase Latin. This module gets us there.

The romaniser is deliberately simple (no full schwa-deletion model). We never
compare romanised strings exactly; we compare *keys* (see `lkey`, `pkey`) that
smooth over spelling variants such as udhaar/udhar/udhār.
"""
from __future__ import annotations

import re
import unicodedata

_VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ii", "उ": "u", "ऊ": "uu", "ऋ": "ri",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e",
    "ऎ": "e", "ऒ": "o",            # short e/o (Kannada ಎ ಒ map here)
}
_MATRAS = {
    "ा": "aa", "ि": "i", "ी": "ii", "ु": "u", "ू": "uu", "ृ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॉ": "o", "ॅ": "e",
    "ॆ": "e", "ॊ": "o",            # short e/o matras (Kannada ೆ ೊ)
}
_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh", "ष": "sh", "स": "s", "ह": "h",
    "ळ": "l", "ऱ": "r", "ऴ": "l",   # ळ ऱ ऴ (Kannada ಳ ಱ ೞ)
    # precomposed nukta forms
    "क़": "q", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "r", "ढ़": "rh", "फ़": "f", "य़": "y",
}
_NUKTA_MAP = {"क": "q", "ख": "kh", "ग": "g", "ज": "z", "ड": "r", "ढ": "rh", "फ": "f"}
_VIRAMA = "्"
_NUKTA = "़"
_ANUSVARA = {"ं": "n", "ँ": "n"}
_VISARGA = "ः"
_DIGITS = {chr(0x0966 + i): str(i) for i in range(10)}
_PUNCT = {"।": ".", "॥": "."}

_DEVANAGARI_RE = re.compile("[ऀ-ॿ]")
_KANNADA_RE = re.compile("[ಀ-೿]")
_INDIC_RE = re.compile("[ऀ-ॿঀ-৿ಀ-೿]")


def has_devanagari(text: str) -> bool:
    return bool(_DEVANAGARI_RE.search(text))


def has_kannada(text: str) -> bool:
    return bool(_KANNADA_RE.search(text))


def has_indic(text: str) -> bool:
    return bool(_INDIC_RE.search(text))


def _to_devanagari(text: str) -> str:
    """Kannada and Bengali share Devanagari's ISCII layout at a fixed offset, so mapping them
    onto Devanagari lets one romaniser serve all three scripts."""
    out = []
    for ch in text:
        cp = ord(ch)
        if 0x0C80 <= cp <= 0x0CFF:
            cp -= 0x380
        elif 0x0980 <= cp <= 0x09FF:
            cp -= 0x80
        out.append(chr(cp))
    return "".join(out)


def devanagari_to_kannada(text: str) -> str:
    """रमेश कुमार -> ರಮೇಶ್ ಕುಮಾರ್, so Timbre kn-IN pronounces seeded names natively."""
    text = unicodedata.normalize("NFD", text).replace(_NUKTA, "")
    text = unicodedata.normalize("NFC", text)
    text = text.replace("ँ", "ं").replace("ॉ", "ॊ").replace("ऑ", "ऒ")
    out = []
    chars = list(text)
    for i, ch in enumerate(chars):
        cp = ord(ch)
        if 0x0900 <= cp <= 0x097F:
            out.append(chr(cp + 0x380))
            nxt = chars[i + 1] if i + 1 < len(chars) else ""
            if ch in _CONSONANTS and not (nxt and 0x0900 <= ord(nxt) <= 0x097F):
                out.append("್")         # word-final consonant needs an explicit virama in Kannada
        else:
            out.append(ch)
    return "".join(out)


def romanize(text: str) -> str:
    """Romanise Devanagari / Kannada / Bengali in `text`; Latin passes through unchanged."""
    if not has_indic(text):
        return text
    text = text.replace("‌", "").replace("‍", "")   # ZWNJ/ZWJ, common in Kannada
    text = unicodedata.normalize("NFC", _to_devanagari(text))
    out: list[str] = []
    chars = list(text)
    i = 0
    n = len(chars)
    while i < n:
        ch = chars[i]
        if ch in _CONSONANTS:
            base = _CONSONANTS[ch]
            j = i + 1
            if j < n and chars[j] == _NUKTA:
                base = _NUKTA_MAP.get(ch, base)
                j += 1
            nxt = chars[j] if j < n else ""
            if nxt in _MATRAS:
                out.append(base + _MATRAS[nxt])
                j += 1
            elif nxt == _VIRAMA:
                out.append(base)
                j += 1
            else:
                # inherent schwa; dropped at end of word (राम -> raam, not raama)
                at_word_end = (not nxt) or not _is_devanagari_letter(nxt)
                if nxt in _ANUSVARA or nxt == _VISARGA:
                    at_word_end = False
                out.append(base if at_word_end else base + "a")
            i = j
            continue
        if ch in _VOWELS:
            out.append(_VOWELS[ch])
        elif ch in _MATRAS:  # stray matra
            out.append(_MATRAS[ch])
        elif ch in _ANUSVARA:
            out.append(_ANUSVARA[ch])
        elif ch == _VISARGA:
            out.append("h")
        elif ch in _DIGITS:
            out.append(_DIGITS[ch])
        elif ch in _PUNCT:
            out.append(_PUNCT[ch])
        elif ch in (_VIRAMA, _NUKTA):
            pass
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _is_devanagari_letter(ch: str) -> bool:
    return ch in _CONSONANTS or ch in _VOWELS or ch in _MATRAS or ch in _ANUSVARA \
        or ch == _VIRAMA or ch == _NUKTA or ch == _VISARGA


_DOUBLE_RE = re.compile(r"(.)\1+")


def lkey(word: str) -> str:
    """Light key: normalises vowel length and doubled letters, keeps aspirates.

    Used for number words, where aspiration matters (saat=7 vs saath=60).
    """
    w = word.lower()
    w = re.sub(r"[^a-z0-9]", "", w)
    w = w.replace("ee", "i").replace("ii", "i").replace("oo", "u").replace("uu", "u")
    w = w.replace("w", "v")
    w = _DOUBLE_RE.sub(r"\1", w)
    return w


def pkey(word: str) -> str:
    """Aggressive phonetic key for names and keywords (aspiration/sibilants merged)."""
    w = lkey(word)
    for a, b in (("chh", "ch"), ("sh", "s"), ("ph", "f"), ("z", "j"), ("q", "k"),
                 ("kh", "k"), ("gh", "g"), ("jh", "j"), ("th", "t"), ("dh", "d"),
                 ("bh", "b"), ("rh", "r"), ("y", "i")):
        w = w.replace(a, b)
    w = _DOUBLE_RE.sub(r"\1", w)
    # trailing schwa / long-a variation: sharma/sharmaa, udhar/udhaar
    if len(w) > 3 and w.endswith("a"):
        w = w[:-1]
    return w
