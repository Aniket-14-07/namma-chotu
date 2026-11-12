"""Customer-name spotting with phonetic fuzzy matching."""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Iterable

from .lexicon import NAME_SUFFIXES, PARTICLES, STOP
from .normalize import SEP
from .numbers import token_kind
from .romanize import pkey

FUZZY_MIN = 0.84
_JI = pkey("ji")


@dataclass
class Mention:
    start: int
    end: int
    candidates: list[int] = field(default_factory=list)   # customer ids, best first
    score: float = 0.0
    known: bool = True
    surface: str = ""
    particle: str | None = None     # from a glued Kannada case ending (rameshge -> dative)


def _eligible(tok: str) -> bool:
    if tok == SEP:
        return False
    if token_kind(tok)[0] in ("digit", "word", "mult", "frac", "cur"):
        return False
    return pkey(tok) not in STOP


def find_mentions(tokens: list[str], customers: Iterable) -> list[Mention]:
    customers = list(customers)
    used = [False] * len(tokens)
    mentions: list[Mention] = []
    for n in (3, 2, 1):
        for i in range(0, len(tokens) - n + 1):
            if any(used[i:i + n]):
                continue
            span = tokens[i:i + n]
            core = span[:-1] if n > 1 and pkey(span[-1]) == _JI else span
            if not core or not all(_eligible(t) for t in core):
                continue
            key = pkey("".join(span))
            scored: list[tuple[float, int]] = []
            full_exact: list[int] = []
            for c in customers:
                best = 0.0
                for alias, akind in c.keys.items():
                    if alias == key:
                        best = 1.0
                        if akind in ("full", "hi"):
                            full_exact.append(c.id)
                        break
                    if len(key) >= 4 and len(alias) >= 4:
                        r = SequenceMatcher(None, key, alias).ratio()
                        if r > best:
                            best = r
                if best >= FUZZY_MIN:
                    scored.append((best, c.id))
            if not scored:
                continue
            scored.sort(key=lambda x: -x[0])
            top = scored[0][0]
            if full_exact:
                cands = full_exact          # "Sharma ji" -> the customer called Sharma Ji
            else:
                cands = [cid for s, cid in scored if s >= top - 0.03]
            mentions.append(Mention(start=i, end=i + n, candidates=cands, score=top, known=True,
                                    surface=" ".join(span)))
            for k in range(i, i + n):
                used[k] = True
    # Kannada glues case endings onto names: "rameshge", "sureshavru", "rameshinda".
    for i, tok in enumerate(tokens):
        if used[i] or tok == SEP or not tok.isalpha():
            continue
        for suf, particle in NAME_SUFFIXES:
            if not tok.endswith(suf) or len(tok) - len(suf) < 3:
                continue
            core = tok[: -len(suf)]
            key = pkey(core)
            if key in STOP:
                continue
            cands = [c.id for c in customers if key in c.keys]
            if not cands and len(key) >= 4:
                cands = [c.id for c in customers
                         if any(len(a) >= 4 and SequenceMatcher(None, key, a).ratio() >= 0.9 for a in c.keys)]
            if cands:
                full = [c.id for c in customers if c.id in cands and c.keys.get(key) in ("full", "hi")]
                mentions.append(Mention(start=i, end=i + 1, candidates=full or cands, score=1.0, known=True,
                                        surface=core, particle=particle))
                used[i] = True
                break
    mentions.sort(key=lambda m: m.start)
    return mentions


def find_unknown_name(tokens: list[str], lo: int = 0, hi: int | None = None) -> Mention | None:
    """A new customer name: eligible word(s) right before a particle (ka/ne/ko/se/ji...)."""
    hi = len(tokens) if hi is None else hi
    for i in range(lo, hi):
        if pkey(tokens[i]) in PARTICLES and i > lo and _eligible(tokens[i - 1]):
            start = i - 1
            if start - 1 >= lo and _eligible(tokens[start - 1]):
                start -= 1
            surface = " ".join(tokens[start:i])
            if len(surface) < 2:
                continue
            return Mention(start=start, end=i, candidates=[], score=0.0, known=False, surface=surface)
    return None
