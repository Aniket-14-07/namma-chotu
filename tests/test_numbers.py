"""Number intelligence: the PS2 'numbers under noise' requirement, on transcripts."""
import pytest

from app.nlu.normalize import tokenize
from app.nlu.numbers import find_numbers
from app.numwords import HI_1_99, fmt_inr, words_en, words_hi


def amounts(text):
    return [s.paise // 100 for s in find_numbers(tokenize(text))]


@pytest.mark.parametrize("text,expected", [
    ("340", 340),
    ("₹340", 340),
    ("Rs. 340", 340),
    ("340/-", 340),
    ("1,250", 1250),
    ("₹1,00,000", 100000),
    ("teen sau chaalis", 340),
    ("teen sau chalis rupaye", 340),
    ("three-forty", 340),
    ("three forty", 340),
    ("Three hundred forty", 340),
    ("three hundred and forty", 340),
    ("barah sau pachaas", 1250),
    ("twelve fifty", 1250),
    ("do hazaar paanch sau", 2500),
    ("teen chalis", 340),
    ("तीन सौ चालीस", 340),
    ("३४०", 340),
    ("3 sau 40", 340),
    ("dedh sau", 150),
    ("dhai hazaar", 2500),
    ("sadhe teen sau", 350),
    ("sawa do sau", 225),
    ("paune do sau", 175),
    ("ek lakh bees hazaar", 120000),
    ("5k", 5000),
    ("forty five", 45),
    ("pachchis", 25),
    ("do rupaye", 2),
])
def test_amount_forms(text, expected):
    assert amounts(text)[0] == expected


@pytest.mark.parametrize("text", ["likh do", "Ramesh ke saath", "ek baar", "kar do"])
def test_weak_words_are_not_amounts(text):
    assert amounts(text) == []


def test_verb_do_before_digits_is_not_two():
    assert amounts("likh do 340") == [340]


def test_every_hindi_number_word_roundtrips():
    """Prisma 'verbatim' mode spells numbers in Devanagari: all 1-99 must parse back."""
    for n in range(1, 100):
        got = amounts(HI_1_99[n] + " रुपये")
        assert got == [n], (n, HI_1_99[n], got)


@pytest.mark.parametrize("n", [7, 60, 99, 340, 1250, 2500, 100000, 120340, 10000000])
def test_spoken_hindi_words_roundtrip(n):
    assert amounts(words_hi(n) + " रुपये") == [n]


@pytest.mark.parametrize("n", [7, 45, 340, 1250, 100000])
def test_spoken_english_words_roundtrip(n):
    assert amounts(words_en(n) + " rupees") == [n]


def test_inr_format():
    assert fmt_inr(124000) == "₹1,240"
    assert fmt_inr(12345678900) == "₹12,34,56,789"
    assert fmt_inr(34050) == "₹340.50"
