"""Conversational behaviour, lists, time, re-asking."""
from app.llm import to_clauses
from tests.test_scenarios import bal, say


def run(session, text, commands):
    return session.handle(text, clauses=to_clauses(text, commands, session.ledger.customers))


def test_chat_reply_is_spoken(session):
    r = run(session, "dukaan mein Diwali ke liye kya stock rakhun?",
            [{"intent": "CHAT", "reply": "दिवाली पर मिठाई, ड्राई फ्रूट्स और दीये ज़्यादा बिकते हैं।"}])
    assert "दिवाली" in r.display and not r.events


def test_time_question_rules(session):
    r = say(session, "abhi kitna baja hai")
    assert r.intents == ["TIME"] and ("बजे" in r.display or "PM" in r.display)


def test_list_customers(session):
    say(session, "Suresh ka 500 udhaar")
    for utt in ("sabka hisaab batao", "customers ki list do"):
        r = say(session, utt)
        assert "Suresh" in r.display or "सुरेश" in r.display
        assert "\n•" in r.display and "\n•" not in r.speak


def test_list_entries_today(session):
    say(session, "Suresh ka 500 udhaar", "Suresh ne 100 diye")
    r = say(session, "aaj ki entries ki list")
    assert r.display.count("\n•") == 2


def test_customer_history_llm(session):
    say(session, "Suresh ka 500 udhaar")
    r = run(session, "Suresh ka pura hisaab", [{"intent": "QUERY", "query": "CUSTOMER_HISTORY", "customer": "Suresh Yadav", "heard_name": "Suresh"}])
    assert "500" in r.display and "लेना" in r.display


def test_yes_to_open_question_reasks(session):
    r = say(session, "Suresh ka udhaar likho")
    assert r.pending and r.pending["kind"] == "need_amount"
    r = say(session, "haan")
    assert r.pending and r.pending["kind"] == "need_amount"
    say(session, "300")
    assert bal(session.ledger, "Suresh Yadav") == 300


def test_settle_all_then_remove(session):
    say(session, "Suresh ka 500 udhaar")
    r = run(session, "Suresh has cleared all the dues, remove his name",
            [{"intent": "TXN", "customer": "Suresh Yadav", "heard_name": "Suresh", "kind": "PAYMENT", "settle_all": True},
             {"intent": "REMOVE_CUSTOMER", "customer": "Suresh Yadav", "heard_name": "Suresh"}])
    assert any(e["type"] == "customer_removed" for e in r.events)
    assert "Suresh Yadav" not in {c.name for c in session.ledger.customers}


def test_remove_refused_when_due(session):
    say(session, "Suresh ka 500 udhaar")
    r = run(session, "Suresh ko hata do", [{"intent": "REMOVE_CUSTOMER", "customer": "Suresh Yadav", "heard_name": "Suresh"}])
    assert not any(e["type"] == "customer_removed" for e in r.events) and "500" in r.display
