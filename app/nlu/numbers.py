"""Spoken-amount parsing for Hindi, English and Hinglish.

Handles: "340", "1,250", "₹340", "teen sau chaalis", "barah sau pachaas",
"do hazaar paanch sau", "three hundred forty", "three-forty" (colloquial 3|40),
"teen chalis", "dedh sau" (150), "dhai hazaar" (2500), "sadhe teen sau" (350),
"sawa do sau" (225), "paune do sau" (175), "3 sau 40", Devanagari digits
(via romanisation upstream).

Output is integer **paise**. Every parse carries flags so the dialogue layer can
decide whether to read back, or to ask.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .romanize import lkey

# --- lexicon -------------------------------------------------------------
_HI_1_99: dict[int, list[str]] = {
    0: ["shunya", "zero", "sifar"],
    1: ["ek"], 2: ["do"], 3: ["teen", "tin"], 4: ["char", "chaar"],
    5: ["paanch", "panch", "paach"], 6: ["chhah", "chhe", "chhai", "che", "chah", "cheh"],
    7: ["saat"], 8: ["aath", "aat"], 9: ["nau", "now"], 10: ["das", "dus"],
    11: ["gyarah", "gyara", "igyarah"], 12: ["barah", "bara", "baarah"],
    13: ["terah", "tera"], 14: ["chaudah", "chauda", "chodah"], 15: ["pandrah", "pandra", "pandhra"],
    16: ["solah", "sola"], 17: ["satrah", "satra"], 18: ["atharah", "athara", "attharah"],
    19: ["unnis", "unees", "unis"], 20: ["bees", "bis"],
    21: ["ikkis", "ikkees"], 22: ["bais", "baais", "baees"], 23: ["teis", "teyis", "tyees"],
    24: ["chaubis", "chaubees", "chobis"], 25: ["pachis", "pachchis", "pachees", "pachchees"],
    26: ["chhabbis", "chhabbees", "chabbis"], 27: ["sattais", "sataees", "sattaees"],
    28: ["athais", "atthais", "athaees", "atthaees"], 29: ["untis", "unatis", "untees"],
    30: ["tees", "tis"], 31: ["iktis", "ikattis", "iktees", "ikattees"], 32: ["battis", "battees", "batis"],
    33: ["taintis", "tetis", "taintees", "tentis"], 34: ["chautis", "chauntis", "chauntees", "chotis"],
    35: ["paintis", "paintees", "pentis"], 36: ["chhattis", "chhattees", "chattis"],
    37: ["saintis", "saintees", "sentis"], 38: ["artis", "adtis", "adtees", "artees"],
    39: ["untalis", "unchalis", "untalees", "unchaalis", "unchaalees"],
    40: ["chalis", "chaalis", "chalees", "chaalees"],
    41: ["iktalis", "iktalees", "iktaalis"], 42: ["bayalis", "bayalees", "byalis", "bayaalis"],
    43: ["taintalis", "tetalis", "taintalees", "tentalis"], 44: ["chavalis", "chauvalis", "chauwalis", "chavalees", "chaualis"],
    45: ["paintalis", "paintalees", "pentalis"], 46: ["chhiyalis", "chhiyalees", "chiyalis"],
    47: ["saintalis", "saintalees", "sentalis"], 48: ["artalis", "adtalis", "artalees", "adtalees"],
    49: ["unchas", "unchaas", "unanchas"], 50: ["pachas", "pachaas", "pachaas"],
    51: ["ikyavan", "ikyaavan", "ikyawan"], 52: ["bavan", "baavan", "bawan"],
    53: ["tirpan", "tirepan", "tirepan"], 54: ["chauvan", "chauwan", "chauvan"],
    55: ["pachpan"], 56: ["chhappan", "chappan"], 57: ["sattavan", "sattawan"],
    58: ["atthavan", "athavan", "atthawan"], 59: ["unsath", "unsaath", "unasath"],
    60: ["saath", "sath"],
    61: ["iksath", "iksaath"], 62: ["basath", "baasath", "basaath"], 63: ["tirsath", "tresath", "tirsaath"],
    64: ["chausath", "chausaath"], 65: ["painsath", "painsaath", "pensath"],
    66: ["chhiyasath", "chhiyasaath"], 67: ["sarsath", "sadsath", "sarsaath"],
    68: ["arsath", "adsath", "arsaath"], 69: ["unhattar"],
    70: ["sattar", "sattar"], 71: ["ikhattar"], 72: ["bahattar"], 73: ["tihattar"],
    74: ["chauhattar"], 75: ["pachhattar", "pachattar"], 76: ["chhihattar", "chihattar"],
    77: ["satattar", "sathattar"], 78: ["athhattar", "athattar"], 79: ["unasi", "unaasi", "unyasi"],
    80: ["assi", "asi"], 81: ["ikyasi", "ikyaasi"], 82: ["bayasi", "bayaasi"], 83: ["tirasi", "tiraasi"],
    84: ["chaurasi", "chauraasi"], 85: ["pachasi", "pachaasi"], 86: ["chhiyasi", "chhiyaasi"],
    87: ["sattasi", "sattaasi"], 88: ["athasi", "atthasi", "atthaasi"], 89: ["navasi", "nawasi", "navaasi"],
    90: ["nabbe", "nabe", "nabbey"], 91: ["ikyanve", "ikyaanve"], 92: ["banve", "baanve"],
    93: ["tiranve", "tiraanve"], 94: ["chauranve", "chauraanve"], 95: ["pachanve", "pachaanve"],
    96: ["chhiyanve", "chhiyaanve"], 97: ["sattanve", "sattaanve"], 98: ["attanve", "atthaanve", "attaanve"],
    99: ["ninyanve", "ninyaanve", "ninnyanve"],
}
_EN_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_EN_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
            "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}

MULTIPLIERS = {
    "sau": 100, "so": 100, "sao": 100, "hundred": 100,
    "hazar": 1000, "hajar": 1000, "hazaar": 1000, "hajaar": 1000, "thousand": 1000, "k": 1000,
    "lakh": 100_000, "lac": 100_000, "lakhs": 100_000, "lacs": 100_000, "lak": 100_000,
    "crore": 10_000_000, "karod": 10_000_000, "karor": 10_000_000, "cr": 10_000_000,
}
# fractional prefixes: (kind, value)
_FRACTIONS = {
    "dedh": ("abs", 1.5), "derh": ("abs", 1.5), "dhedh": ("abs", 1.5),
    "dhai": ("abs", 2.5), "dhaai": ("abs", 2.5), "adhai": ("abs", 2.5),
    "sadhe": ("plus", 0.5), "saade": ("plus", 0.5), "sade": ("plus", 0.5), "saadhe": ("plus", 0.5),
    "sava": ("plus", 0.25), "sawa": ("plus", 0.25), "savva": ("plus", 0.25),
    "paune": ("minus", 0.25), "pone": ("minus", 0.25), "paone": ("minus", 0.25),
}
# Words that are numbers only with numeric context ("likh do", "ke saath", "ek baar").
WEAK_NUMBER_KEYS = {lkey(w) for w in ("do", "ek", "saath", "sath", "so", "sao", "nau", "now", "k", "cr")}
CURRENCY_WORDS = {"rupaye", "rupaiye", "rupay", "rupees", "rupee", "rupe", "rs", "inr", "rupya",
                  "rupiya", "rupaiya", "rupaya", "rupaiyaa", "₹", "rupaye", "paisa", "paise"}
CURRENCY_KEYS = {lkey(w) for w in CURRENCY_WORDS}

_WORD_VALUE: dict[str, int] = {}
for _v, _ws in _HI_1_99.items():
    for _w in _ws:
        _WORD_VALUE.setdefault(lkey(_w), _v)
for _w, _v in {**_EN_UNITS, **_EN_TENS}.items():
    _WORD_VALUE[lkey(_w)] = _v
# Devanagari spellings (Prisma `verbatim`/`codemix` output) romanised the same way the
# transcript will be, so medial-schwa differences (अड़तीस -> "aratiis") can't cause misses.
def _add_devanagari_forms() -> None:
    from ..numwords import HI_1_99
    from .romanize import romanize
    alt = {44: "चौवालीस", 49: "उनचास", 59: "उनसठ", 63: "तिरसठ", 64: "चौसठ", 67: "सरसठ", 79: "उनासी",
           89: "नवासी", 91: "इक्यानबे", 92: "बानबे", 93: "तिरानबे", 94: "चौरानबे", 95: "पचानबे",
           96: "छियानबे", 97: "सत्तानबे", 98: "अठानवे", 99: "निन्यानबे", 6: "छः", 5: "पांच", 1: "एक"}
    for n in range(1, 100):
        _WORD_VALUE.setdefault(lkey(romanize(HI_1_99[n])), n)
    for n, w in alt.items():
        _WORD_VALUE.setdefault(lkey(romanize(w)), n)
    for w, v in (("सौ", 100), ("हज़ार", 1000), ("हजार", 1000), ("लाख", 100_000), ("करोड़", 10_000_000),
                 ("सैकड़ा", 100)):
        MULTIPLIERS.setdefault(romanize(w), v)
    for w, v in (("डेढ़", ("abs", 1.5)), ("ढाई", ("abs", 2.5)), ("साढ़े", ("plus", 0.5)),
                 ("सवा", ("plus", 0.25)), ("पौने", ("minus", 0.25))):
        _FRACTIONS.setdefault(romanize(w), v)
    for w in ("रुपये", "रुपए", "रुपया", "रूपये", "पैसे"):
        CURRENCY_KEYS.add(lkey(romanize(w)))


_add_devanagari_forms()


# ---- Kannada -------------------------------------------------------------------------
# Kiranas in Karnataka speak amounts in Kannada ("munnoora nalavattu", "eradu saavira").
_KN_UNITS = {1: ["ondu", "ond"], 2: ["eradu", "yeradu", "erdu"], 3: ["mooru", "muru"], 4: ["naalku", "nalku", "naaku"],
             5: ["aidu", "eidu", "aydu"], 6: ["aaru"], 7: ["elu", "eelu", "yelu", "yeelu"], 8: ["entu", "yentu"],
             9: ["ombattu", "ombhattu"], 10: ["hattu"]}
_KN_TEENS = {11: ["hannondu"], 12: ["hanneradu"], 13: ["hadimooru"], 14: ["hadinaalku", "hadinalku"],
             15: ["hadinaidu"], 16: ["hadinaaru"], 17: ["hadinelu", "hadineelu"], 18: ["hadinentu"],
             19: ["hattombattu"]}
_KN_TENS = {20: ["ippattu"], 30: ["moovattu", "muvattu"], 40: ["nalavattu", "nalvattu"], 50: ["aivattu", "aivatu"],
            60: ["aravattu"], 70: ["eppattu"], 80: ["enbattu", "embattu"], 90: ["tombattu", "thombattu"]}
_KN_HUNDREDS = {200: ["innooru", "innoora"], 300: ["munnooru", "munnoora"],
                400: ["naanooru", "nanooru", "naanoora"], 500: ["ainooru", "ainoora"], 600: ["aarunooru", "aarnooru"],
                700: ["elunooru", "eelnooru"], 800: ["entunooru", "entnooru"], 900: ["ombainooru", "ombaynooru"]}
_KN_SCRIPT = {1: "ಒಂದು", 2: "ಎರಡು", 3: "ಮೂರು", 4: "ನಾಲ್ಕು", 5: "ಐದು", 6: "ಆರು", 7: "ಏಳು", 8: "ಎಂಟು", 9: "ಒಂಬತ್ತು",
              10: "ಹತ್ತು", 11: "ಹನ್ನೊಂದು", 12: "ಹನ್ನೆರಡು", 13: "ಹದಿಮೂರು", 14: "ಹದಿನಾಲ್ಕು", 15: "ಹದಿನೈದು",
              16: "ಹದಿನಾರು", 17: "ಹದಿನೇಳು", 18: "ಹದಿನೆಂಟು", 19: "ಹತ್ತೊಂಬತ್ತು", 20: "ಇಪ್ಪತ್ತು", 30: "ಮೂವತ್ತು",
              40: "ನಲವತ್ತು", 50: "ಐವತ್ತು", 60: "ಅರವತ್ತು", 70: "ಎಪ್ಪತ್ತು", 80: "ಎಂಬತ್ತು", 90: "ತೊಂಬತ್ತು",
              200: "ಇನ್ನೂರು", 300: "ಮುನ್ನೂರು", 400: "ನಾನೂರು", 500: "ಐನೂರು", 600: "ಆರುನೂರು", 700: "ಏಳುನೂರು",
              800: "ಎಂಟುನೂರು", 900: "ಒಂಬೈನೂರು"}
_KN_STEMS = {20: "ippatt", 30: "moovatt", 40: "nalavatt", 50: "aivatt", 60: "aravatt", 70: "eppatt", 80: "enbatt",
             90: "tombatt"}
_KN_UNIT_COMPOUND = {1: ["ondu", "onda"], 2: ["eradu"], 3: ["mooru", "amooru"], 4: ["naalku", "anaalku"],
                     5: ["aidu", "aidu"], 6: ["aaru", "aaru"], 7: ["elu", "eelu"], 8: ["entu"], 9: ["ombattu"]}


def _add_kannada_forms() -> None:
    from .romanize import romanize

    def reg(word: str, val: int) -> None:
        k = lkey(word)
        _WORD_VALUE.setdefault(k, val)
        if len(k) > 3 and k[-1] in "aeiou":      # spoken/written without the final vowel (munnoor, ippatt)
            _WORD_VALUE.setdefault(k[:-1], val)

    for table in (_KN_UNITS, _KN_TEENS, _KN_TENS, _KN_HUNDREDS):
        for v, ws in table.items():
            for w in ws:
                reg(w, v)
    for tens, stem in _KN_STEMS.items():
        for u, forms in _KN_UNIT_COMPOUND.items():
            for f in forms:
                reg(stem + f, tens + u)
                reg(stem + "a" + f, tens + u)
    for v, w in _KN_SCRIPT.items():
        reg(romanize(w), v)
    for w, m in (("nooru", 100), ("noora", 100), ("ನೂರು", 100), ("ನೂರ", 100), ("saavira", 1000), ("savira", 1000), ("saavirada", 1000), ("ಸಾವಿರ", 1000), ("ಸಾವಿರದ", 1000),
                 ("laksha", 100_000), ("lakshada", 100_000), ("ಲಕ್ಷ", 100_000), ("koti", 10_000_000), ("ಕೋಟಿ", 10_000_000)):
        MULTIPLIERS.setdefault(romanize(w), m)
    for w in ("rupaayi", "rupayi", "rupai", "roopaayi", "ರೂಪಾಯಿ", "ರೂ", "taka", "taakaa"):
        CURRENCY_KEYS.add(lkey(romanize(w)))
    WEAK_NUMBER_KEYS.update({lkey("ondu"), lkey("ond")})


_add_kannada_forms()
_MULT_KEYS = {lkey(k): v for k, v in MULTIPLIERS.items()}
_FRAC_KEYS = {lkey(k): v for k, v in _FRACTIONS.items()}
_EN_TENS_KEYS = {lkey(k) for k in _EN_TENS}
_CONNECTORS = {"aur", "and", "or"}
# words whose phonetic key collides with a number word: ninne (Kannada "yesterday") ~ "nine"
_NOT_NUMBERS = {"ninne", "ninnee", "ninnae", "monne", "naale"}  # "teen sau aur chalis", "one hundred and forty"


@dataclass
class NumberSpan:
    start: int          # token index (inclusive)
    end: int            # token index (exclusive)
    paise: int
    flags: set[str] = field(default_factory=set)
    has_currency: bool = False

    @property
    def rupees(self) -> float:
        return self.paise / 100


def _digit_value(tok: str) -> float | None:
    t = tok.replace(",", "")
    if t.endswith("/-"):
        t = t[:-2]
    try:
        if t.count(".") <= 1 and t.replace(".", "").isdigit():
            return float(t)
    except ValueError:
        return None
    return None


def token_kind(tok: str) -> tuple[str, float | tuple | None]:
    """Classify a single token -> ('digit'|'word'|'mult'|'frac'|'conn'|'cur'|'other', value)."""
    dv = _digit_value(tok)
    if dv is not None:
        return "digit", dv
    if tok in _NOT_NUMBERS:
        return "other", None
    k = lkey(tok)
    if not k:
        return "other", None
    if k in _MULT_KEYS:
        return "mult", _MULT_KEYS[k]
    if k in _FRAC_KEYS:
        return "frac", _FRAC_KEYS[k]
    if k in _WORD_VALUE:
        return "word", _WORD_VALUE[k]
    if tok in _CONNECTORS:
        return "conn", None
    if k in CURRENCY_KEYS:
        return "cur", None
    return "other", None


def find_numbers(tokens: list[str]) -> list[NumberSpan]:
    """Find maximal number spans in a token list and evaluate them."""
    spans: list[NumberSpan] = []
    i = 0
    n = len(tokens)
    while i < n:
        kind, _ = token_kind(tokens[i])
        if kind not in ("digit", "word", "mult", "frac"):
            i += 1
            continue
        j = i
        group: list[tuple[str, object, int]] = []
        while j < n:
            k2, v2 = token_kind(tokens[j])
            if k2 in ("digit", "word", "mult", "frac"):
                group.append((k2, v2, j))
                j += 1
                continue
            if k2 == "conn" and group and j + 1 < n and token_kind(tokens[j + 1])[0] in ("digit", "word"):
                j += 1  # skip connector inside a number
                continue
            break
        span = _evaluate(group, tokens)
        if span is not None:
            # trailing currency word?
            if span.end < n and token_kind(tokens[span.end])[0] == "cur":
                span.has_currency = True
            elif span.start > 0 and token_kind(tokens[span.start - 1])[0] == "cur":
                span.has_currency = True
            spans.append(span)
            i = span.end
        else:
            i = j if j > i else i + 1
    return spans


def _evaluate(group: list[tuple[str, object, int]], tokens: list[str]) -> NumberSpan | None:
    if not group:
        return None
    # Weak lone words ("do", "ek", "saath") are only numbers with numeric context.
    if len(group) == 1 and group[0][0] == "word" and lkey(tokens[group[0][2]]) in WEAK_NUMBER_KEYS:
        nxt = group[0][2] + 1
        if not (nxt < len(tokens) and token_kind(tokens[nxt])[0] == "cur"):
            return None
    # A lone multiplier/fraction word like "sau" with nothing else is ambiguous only for "so"/"k".
    if len(group) == 1 and group[0][0] == "mult" and lkey(tokens[group[0][2]]) in {"so", "sao", "k", "cr"}:
        return None
    # Leading weak "do" before a non-number continuation like "do sau" is fine; but "likh do 340"
    # yields group [do, 340] -> treat "do" adjacent to a digit as the verb, not a number.
    if len(group) >= 2 and group[0][0] == "word" and lkey(tokens[group[0][2]]) in WEAK_NUMBER_KEYS \
            and group[1][0] == "digit":
        group = group[1:]

    flags: set[str] = set()
    total = 0.0
    current = 0.0
    last_kind = None
    frac: tuple[str, float] | None = None
    start = group[0][2]
    end = group[-1][2] + 1
    for kind, val, _idx in group:
        if kind in ("digit", "word"):
            v = float(val)  # type: ignore[arg-type]
            if last_kind in ("digit", "word"):
                # adjacency without multiplier: "teen chalis" / "three forty" / "twelve fifty"
                if current >= 100 and current % 100 == 0 and 1 <= v <= 99 and last_kind == "word":
                    current += v                     # Kannada: munnooru nalavattu -> 340
                elif 1 <= current <= 99 and 10 <= v <= 99 and current == int(current):
                    current = current * 100 + v
                    flags.add("colloquial_hundreds")
                elif current >= 20 and current % 10 == 0 and current < 100 and 1 <= v <= 9:
                    current += v  # "forty five" / "twenty 5"
                elif 1 <= current <= 9 and v >= 100 and kind == "digit":
                    # "2 340" -> separate numbers; stop here
                    end = _idx
                    break
                else:
                    end = _idx
                    flags.add("split_adjacent")
                    break
            else:
                current += v
            if kind == "digit" and v != int(v):
                flags.add("decimal")
        elif kind == "mult":
            m = float(val)  # type: ignore[arg-type]
            base = current if current else 1.0
            if frac:
                fk, fv = frac
                if fk == "abs":
                    base = fv
                elif fk == "plus":
                    base = (current or 0) + fv
                elif fk == "minus":
                    base = (current or 0) - fv
                frac = None
                flags.add("fraction")
            if m >= 1000:
                total += base * m
                current = 0.0
            else:
                current = base * m
        elif kind == "frac":
            frac = val  # type: ignore[assignment]
        last_kind = kind
    if frac:  # "dedh" with no multiplier: means 1.5 of something unknown
        flags.add("dangling_fraction")
    value = total + current
    if value <= 0 and not any(k in ("digit",) for k, _, _ in group):
        return None
    paise = int(round(value * 100))
    return NumberSpan(start=start, end=end, paise=paise, flags=flags)


def parse_amount_text(text: str) -> int | None:
    """Convenience: parse the first amount in a whitespace-tokenised string -> paise."""
    from .normalize import tokenize
    spans = find_numbers(tokenize(text))
    return spans[0].paise if spans else None
