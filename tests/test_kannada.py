"""Kannada + Kannada-English + Hindi-Kannada code-mix. Ledger outcomes, not just text."""
from datetime import date

import pytest

from app.nlu.normalize import tokenize
from app.nlu.numbers import find_numbers
from tests.conftest import cid
from tests.test_scenarios import bal, active, say

YDAY, PARSO = date(2026, 11, 10), date(2026, 11, 9)


@pytest.mark.parametrize("text,expected", [
    ("munnooru nalavattu", 340), ("munnoora nalavattu rupaayi", 340), ("ಮುನ್ನೂರ ನಲವತ್ತು", 340),
    ("mooru nooru nalavattu", 340), ("eradu saavira aidu nooru", 2500), ("ಎರಡು ಸಾವಿರ ಐನೂರು", 2500),
    ("saavirada innooru aivattu", 1250), ("ippattaidu", 25), ("ippattu aidu", 25), ("ಇಪ್ಪತ್ತೊಂದು ರೂಪಾಯಿ", 21),
    ("ondu laksha", 100000), ("೩೪೦", 340), ("hattu saavira", 10000),
])
def test_kannada_amounts(text, expected):
    assert [s.paise // 100 for s in find_numbers(tokenize(text))][0] == expected


def test_ninne_is_not_nine():
    assert find_numbers(tokenize("Suresh ninne innooru kottru"))[0].paise == 20000


@pytest.mark.parametrize("utt,name,kind,amt", [
    ("Ramesh Kumar munnooru nalavattu udri", "Ramesh Kumar", "CREDIT", 340),
    ("ರಮೇಶ್ ಕುಮಾರ್ ಮುನ್ನೂರ ನಲವತ್ತು ಉದ್ರಿ", "Ramesh Kumar", "CREDIT", 340),
    ("ರಾಹುಲ್‌ಗೆ ಇನ್ನೂರು ರೂಪಾಯಿ ಉದ್ರಿ ಬರೆಯಿರಿ", "Rahul Verma", "CREDIT", 200),
    ("Rahulge 200 rupaayi saamaan kotte", "Rahul Verma", "CREDIT", 200),       # gave goods TO Rahul
    ("Ramesh Kumar ka munnooru nalavattu udhaar", "Ramesh Kumar", "CREDIT", 340),  # hi+kn code-mix
    ("Amit 1250 udri barko", "Amit Patel", "CREDIT", 1250),
])
def test_kannada_credit(session, utt, name, kind, amt):
    r = say(session, utt)
    t = active(session.ledger, name)
    assert len(t) == 1 and t[0]["kind"] == kind and t[0]["amount_paise"] == amt * 100
    assert r.lang in ("kn", "hi")


@pytest.mark.parametrize("utt,amt,day", [
    ("Suresh ninne innooru kottru", 200, YDAY),
    ("ಸುರೇಶ್ ಮೊನ್ನೆ ಐನೂರು ಕೊಟ್ಟರು", 500, PARSO),
    ("Suresh avarinda 300 tagondu", 300, date(2026, 11, 11)),               # took money FROM Suresh
])
def test_kannada_payment(session, utt, amt, day):
    say(session, "Suresh ka 1000 udhaar")
    say(session, utt)
    pays = [t for t in active(session.ledger, "Suresh Yadav") if t["kind"] == "PAYMENT"]
    assert len(pays) == 1 and pays[0]["amount_paise"] == amt * 100 and pays[0]["txn_date"] == day.isoformat()


def test_kannada_reply_is_kannada_script_with_disclosure(session):
    r = say(session, "ರಮೇಶ್ ಕುಮಾರ್ ಮುನ್ನೂರ ನಲವತ್ತು ಉದ್ರಿ")
    assert r.lang == "kn"
    assert r.display.startswith("ನಾನು ಒಂದು AI ಸಹಾಯಕ")             # AI disclosure on language switch
    assert "ರಮೇಶ್ ಕುಮಾರ್" in r.display and "₹340" in r.display and "ಉದ್ರಿ" in r.display
    assert "340 ರೂಪಾಯಿ" in r.speak


def test_kannada_corrections(session):
    say(session, "Suresh munnooru nalavattu udri", "illa, 430")
    assert bal(session.ledger, "Suresh Yadav") == 430
    say(session, "Amit 340 udri", "340 alla 430")
    assert bal(session.ledger, "Amit Patel") == 430


def test_kannada_duplicate_name_question(session):
    r = say(session, "Ramesh 500 udri")
    assert r.pending and r.lang == "kn" and r.display.endswith("?")
    say(session, "Sharma")
    assert bal(session.ledger, "Ramesh Sharma") == 500


def test_kannada_future_writes_nothing(session):
    say(session, "Suresh 500 udri", "Suresh naale 200 kodtaare")
    assert bal(session.ledger, "Suresh Yadav") == 500


def test_kannada_queries(ledger):
    from app.dialogue import Session
    s = Session("k", ledger)
    s.set_language("kn")
    s.greeting()
    r = s.handle("Ramesh Kumar ottu eshtu baaki?")
    assert "₹900" in r.display and r.lang == "kn"
    s.handle("Suresh 340 udri")
    r = s.handle("ivattu eshtu udri hoytu?")
    assert "₹340" in r.display
    r = s.handle("ಯಾರ ಮೇಲೆ ಜಾಸ್ತಿ ಉದ್ರಿ ಇದೆ")
    assert "ಅತಿ ಹೆಚ್ಚು" in r.display


@pytest.mark.parametrize("utt", ["Ramesh Kumar ko 500 pe byaaj lagao", "Ramesh ge baddi haaku", "Suresh ko loan de do"])
def test_no_lending(session, utt):
    r = say(session, utt)
    assert r.intents == ["REFUSE_LENDING"] and not r.events


@pytest.mark.parametrize("utt", ["Ramesh Kumar ko bolo paise do warna police bulaunga",
                                 "Suresh ko reminder bhejo nahi diya to bezzati karunga"])
def test_no_pressure(session, utt):
    r = say(session, utt)
    assert "REFUSE_PRESSURE" in r.intents and not any(e["type"] == "reminder" for e in r.events)
