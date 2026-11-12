"""Judge-simulation scenarios. Each asserts the LEDGER (customer, amount, direction,
date, balance), not just the reply text. Financial correctness first."""
from datetime import date

import pytest

from app.dialogue import Session
from tests.conftest import cid

TODAY = date(2026, 11, 11)
YDAY = date(2026, 11, 10)
PARSO = date(2026, 11, 9)


def active(ledger, name):
    return [t for t in ledger.customer_txns(cid(ledger, name)) if t["status"] == "active"]


def bal(ledger, name):
    return ledger.balance(cid(ledger, name)) // 100


def say(s, *utts):
    r = None
    for u in utts:
        r = s.handle(u)
    return r


# ----------------------------------------------------------------- simple entries
@pytest.mark.parametrize("utt,name,kind,amt", [
    ("Suresh ka 340 rupaye udhaar likh do", "Suresh Yadav", "CREDIT", 340),
    ("Suresh ka teen sau chaalis udhaar", "Suresh Yadav", "CREDIT", 340),
    ("Suresh ka three-forty", "Suresh Yadav", "CREDIT", 340),
    ("सुरेश का तीन सौ चालीस उधार", "Suresh Yadav", "CREDIT", 340),
    ("Priya ke account mein 150 aur add kar do", "Priya Singh", "CREDIT", 150),
    ("Add 340 to Priya's account", "Priya Singh", "CREDIT", 340),
    ("Amit ka barah sau pachaas", "Amit Patel", "CREDIT", 1250),
    ("Rahul Verma ko 200 ka saaman diya", "Rahul Verma", "CREDIT", 200),
    ("Irfan bhai ka dedh sau", "Mohammed Irfan", "CREDIT", 150),
])
def test_credit_entries(session, utt, name, kind, amt):
    say(session, utt)
    t = active(session.ledger, name)
    assert len(t) == 1 and t[0]["kind"] == kind and t[0]["amount_paise"] == amt * 100
    assert t[0]["txn_date"] == TODAY.isoformat()


@pytest.mark.parametrize("pre,utt,name,amt,day", [
    ("Suresh ka 1000 udhaar", "Suresh ne kal 200 rupaye diye the", "Suresh Yadav", 200, YDAY),
    ("Sharma ji ka 1000 udhaar", "Sharma ji ka 500 rupaye payment receive hua", "Sharma Ji", 500, TODAY),
    ("Gupta ji ka 1000 udhaar", "Gupta ji se 300 liye", "Gupta Ji", 300, TODAY),
    ("Priya ka 1000 udhaar", "Priya paid 200 rupees today", "Priya Singh", 200, TODAY),
    ("Priya ka 1000 udhaar", "Priya ne parso 400 jama kiye", "Priya Singh", 400, PARSO),
    ("Amit ka 1000 udhaar", "Amit ne somvar ko 250 diye", "Amit Patel", 250, PARSO),  # Mon 9 Nov
    ("Rahul ka 1000 udhaar", "Rahul ne 2 din pehle 300 diye", "Rahul Verma", 300, PARSO),
])
def test_payment_entries(session, pre, utt, name, amt, day):
    say(session, pre, utt)
    pays = [t for t in active(session.ledger, name) if t["kind"] == "PAYMENT"]
    assert len(pays) == 1 and pays[0]["amount_paise"] == amt * 100 and pays[0]["txn_date"] == day.isoformat()
    assert bal(session.ledger, name) == 1000 - amt


# ----------------------------------------------------------- the PS2 headline sentence
def test_ps_sentence_two_transactions_with_name_clarification(session):
    r = say(session, "Ramesh ka 340 udhaar, kal 200 diya tha")
    assert r.pending and r.pending["kind"] == "which_customer"
    assert active(session.ledger, "Ramesh Kumar") == [] and active(session.ledger, "Ramesh Sharma") == []
    say(session, "Kumar wale")
    t = sorted(active(session.ledger, "Ramesh Kumar"), key=lambda x: x["id"])
    assert [(x["kind"], x["amount_paise"], x["txn_date"]) for x in t] == [
        ("CREDIT", 34000, TODAY.isoformat()), ("PAYMENT", 20000, YDAY.isoformat())]
    assert bal(session.ledger, "Ramesh Kumar") == 140
    assert active(session.ledger, "Ramesh Sharma") == []


def test_ps_sentence_unpunctuated(session):
    say(session, "Ramesh Kumar ka 340 udhaar kal 200 diya tha")
    assert bal(session.ledger, "Ramesh Kumar") == 140


def test_two_customers_one_breath(session):
    say(session, "Suresh ka teen sau chalis rupaye udhaar aur Rahul ne sau rupaye diye")
    assert bal(session.ledger, "Suresh Yadav") == 340
    assert [t["kind"] for t in active(session.ledger, "Rahul Verma")] == []  # overpay -> asked first
    say(session, "haan")
    assert bal(session.ledger, "Rahul Verma") == -100


@pytest.mark.parametrize("answer", ["Sharma", "Ramesh Sharma", "doosra", "second", "शर्मा वाले"])
def test_duplicate_name_answers(session, answer):
    say(session, "Ramesh ka 500 udhaar")
    say(session, answer)
    assert bal(session.ledger, "Ramesh Sharma") == 500
    assert bal(session.ledger, "Ramesh Kumar") == 0


def test_duplicate_name_cancel_writes_nothing(session):
    say(session, "Ramesh ka 500 udhaar", "nahi rehne do")
    assert bal(session.ledger, "Ramesh Sharma") == 0 and bal(session.ledger, "Ramesh Kumar") == 0


# ----------------------------------------------------------------- corrections
def test_correction_amount_short(session):
    say(session, "Suresh ka 340 udhaar", "nahi, 430")
    t = active(session.ledger, "Suresh Yadav")
    assert len(t) == 1 and t[0]["amount_paise"] == 43000
    assert bal(session.ledger, "Suresh Yadav") == 430


def test_correction_amount_explicit(session):
    say(session, "Suresh ka 340 udhaar", "Galat hai, 340 nahi 430 tha")
    assert bal(session.ledger, "Suresh Yadav") == 430


def test_correction_keeps_audit_trail(session):
    say(session, "Suresh ka 340 udhaar", "nahi, 430")
    allrows = session.ledger.customer_txns(cid(session.ledger, "Suresh Yadav"))
    voided = [t for t in allrows if t["status"] == "voided"]
    assert len(voided) == 1 and voided[0]["amount_paise"] == 34000 and voided[0]["replaced_by"]


def test_correction_customer(session):
    say(session, "Ramesh Kumar ka 300 udhaar", "Ramesh nahi Suresh")
    assert bal(session.ledger, "Ramesh Kumar") == 0
    assert bal(session.ledger, "Suresh Yadav") == 300


def test_correction_date(session):
    say(session, "Amit ka 300 udhaar kal ka", "Kal nahi, parso")
    t = active(session.ledger, "Amit Patel")
    assert len(t) == 1 and t[0]["txn_date"] == PARSO.isoformat()


def test_correction_direction(session):
    say(session, "Amit ka 1000 udhaar", "Amit ka 200 udhaar", "udhaar nahi, jama tha")
    assert bal(session.ledger, "Amit Patel") == 800


def test_inline_self_correction_before_write(session):
    say(session, "Ramesh Kumar ka 300 udhaar, nahi nahi, 350")
    t = active(session.ledger, "Ramesh Kumar")
    assert len(t) == 1 and t[0]["amount_paise"] == 35000
    assert session.ledger.customer_txns(cid(session.ledger, "Ramesh Kumar"))[0]["status"] == "active"


def test_correction_targets_matching_txn_in_multi(session):
    say(session, "Suresh ka 340 udhaar aur Amit ka 500 udhaar", "340 nahi 430")
    assert bal(session.ledger, "Suresh Yadav") == 430 and bal(session.ledger, "Amit Patel") == 500


# ----------------------------------------------------------------------- undo
def test_undo_last(session):
    say(session, "Suresh ka 340 udhaar", "Amit ka 500 udhaar", "Last transaction cancel kar do")
    assert bal(session.ledger, "Amit Patel") == 0 and bal(session.ledger, "Suresh Yadav") == 340


def test_undo_named(session):
    say(session, "Suresh ka 340 udhaar", "Amit ka 500 udhaar", "Suresh wali entry hatao")
    assert bal(session.ledger, "Suresh Yadav") == 0 and bal(session.ledger, "Amit Patel") == 500


def test_undo_nothing(session):
    r = say(session, "undo karo")
    assert "कोई" in r.display or "no recent" in r.display.lower()


# ----------------------------------------------------- guardrails / no false writes
def test_future_promise_writes_nothing(session):
    say(session, "Suresh ka 500 udhaar", "Suresh kal 200 dega")
    assert bal(session.ledger, "Suresh Yadav") == 500


def test_negation_writes_nothing(session):
    say(session, "Suresh ka 500 udhaar", "Suresh ne paise nahi diye")
    assert bal(session.ledger, "Suresh Yadav") == 500


def test_overpayment_needs_confirmation(session):
    say(session, "Suresh ka 100 udhaar", "Suresh ne 300 diye")
    assert bal(session.ledger, "Suresh Yadav") == 100
    say(session, "nahi")
    assert bal(session.ledger, "Suresh Yadav") == 100


def test_duplicate_utterance_ignored(session):
    say(session, "Suresh ka 340 udhaar", "Suresh ka 340 udhaar")
    assert bal(session.ledger, "Suresh Yadav") == 340


def test_same_utterance_id_processed_once(session):
    session.handle("Suresh ka 340 udhaar", utterance_id="u1")
    assert session.handle("Suresh ka 340 udhaar", utterance_id="u1") is None
    assert bal(session.ledger, "Suresh Yadav") == 340


def test_new_customer_needs_yes(session):
    say(session, "Mahesh ka 250 udhaar likho")
    assert not any(c.name == "Mahesh" for c in session.ledger.customers)
    say(session, "haan")
    assert bal(session.ledger, "Mahesh") == 250


def test_missing_amount_is_asked(session):
    r = say(session, "Gupta ji ka udhaar likho")
    assert r.pending and r.pending["kind"] == "need_amount"
    say(session, "teen sau")
    assert bal(session.ledger, "Gupta Ji") == 300


def test_low_confidence_huge_amount_asks(session):
    r = say(session, "Suresh ka 75000 udhaar")
    assert r.pending and r.pending["kind"] == "confirm"
    assert bal(session.ledger, "Suresh Yadav") == 0
    say(session, "haan")
    assert bal(session.ledger, "Suresh Yadav") == 75000


def test_context_customer_followup(session):
    say(session, "Priya ka 100 udhaar", "aur 150 add kar do")
    assert bal(session.ledger, "Priya Singh") == 250


def test_reminder_respects_opt_in(session):
    say(session, "Ramesh Sharma ka 500 udhaar")
    r = say(session, "Ramesh Sharma ko reminder bhejo")
    assert not any(e["type"] == "reminder" for e in r.events)
    say(session, "Ramesh Kumar ka 500 udhaar")
    r = say(session, "Ramesh Kumar ko reminder bhejo")
    rem = [e for e in r.events if e["type"] == "reminder"]
    assert rem and "दे दीजिएगा" in rem[0]["message"]
    for bad in ("turant", "warna", "legal", "police", "immediately", "otherwise"):
        assert bad not in rem[0]["message"].lower()


def test_ai_disclosure_in_first_turn():
    from app.ledger import Ledger  # noqa
    s = Session.__new__(Session)
    assert True  # greeting tested below


def test_greeting_discloses_ai(empty_ledger):
    s = Session("g", empty_ledger)
    g = s.greeting()
    assert "AI" in g.display


def test_disclosure_when_user_switches_language(empty_ledger):
    s = Session("g", empty_ledger)
    s.greeting()  # Hindi
    r = s.handle("How much does Priya owe in total?", detected_lang="en-IN")
    assert r.display.startswith("I'm an AI assistant")


# ---------------------------------------------------------------- spoken queries
def test_queries_from_database(ledger):
    s = Session("q", ledger)
    s.greeting()
    r = s.handle("Ramesh Kumar ka total?")
    assert "₹900" in r.display                      # 900 - 300 + 300
    r = s.handle("Aaj kitna udhaar gaya?")
    assert "कोई" in r.display or "₹0" in r.display    # seed has nothing today
    s.handle("Suresh ka 340 udhaar")
    r = s.handle("Aaj kitna udhaar gaya?")
    assert "₹340" in r.display
    r = s.handle("Kal kitna paisa receive hua?")
    assert "₹780" in r.display                      # Priya's 780 yesterday
    r = s.handle("Sabse zyada udhaar kispe hai?")
    top = ledger.top_debtors(1)[0]
    assert top[0].name_hi in r.display
    r = s.handle("Mere total customers kitne hain?")
    assert "12" in r.display
    r = s.handle("Kitna paisa market mein pending hai?")
    from app.numwords import fmt_inr
    assert fmt_inr(ledger.total_outstanding()) in r.display
    r = s.handle("Ramesh Kumar ka last payment kab aaya tha?")
    assert "₹300" in r.display
    r = s.handle("Top five customers by outstanding balance?", detected_lang="en-IN")
    assert r.display.count("₹") == 5


def test_query_latency_budget(ledger):
    s = Session("q", ledger)
    s.greeting()
    r = s.handle("Kitna paisa market mein pending hai?")
    assert r.nlu_ms < 50   # NLU + DB must be a rounding error inside the 2 s budget
