"""LLM understanding path: JSON commands -> clauses -> dialogue -> ledger (no network; JSON is canned)."""
from app.llm import to_clauses

from tests.conftest import cid


def run(session, text, commands):
    return session.handle(text, clauses=to_clauses(text, commands, session.ledger.customers))


def test_loan_given_is_credit(session):
    r = run(session, "Ramesh Kumar ko 500 loan diya",
            [{"intent": "TXN", "customer": "Ramesh Kumar", "kind": "CREDIT", "amount_rupees": 500}])
    L = session.ledger
    assert L.balance(cid(L, "Ramesh Kumar")) == 50000
    assert "500" in r.display


def test_customer_paid_is_payment(session):
    run(session, "Suresh ko 300 udhaar", [{"intent": "TXN", "customer": "Suresh", "kind": "CREDIT", "amount_rupees": 300}])
    run(session, "Suresh ne 100 diye", [{"intent": "TXN", "customer": "Suresh Yadav", "kind": "PAYMENT", "amount_rupees": 100}])
    assert session.ledger.balance(cid(session.ledger, "Suresh Yadav")) == 20000


def test_unheard_amount_asks_first(session):
    # LLM says 340 but the sentence has no 340 in it -> confirm before writing
    r = run(session, "Ramesh Kumar ka udhaar likho",
            [{"intent": "TXN", "customer": "Ramesh Kumar", "kind": "CREDIT", "amount_rupees": 340}])
    assert r.pending and r.pending["kind"] == "confirm"
    assert session.ledger.balance(cid(session.ledger, "Ramesh Kumar")) == 0


def test_add_customer_and_duplicate(session):
    r = run(session, "naya customer Manjunath Gowda, phone 9876512345",
            [{"intent": "ADD_CUSTOMER", "new_name": "Manjunath Gowda", "phone": "9876512345"}])
    assert any(e["type"] == "customer_created" for e in r.events)
    c = session.ledger.find_by_name("manjunath gowda")
    assert c and c.phone == "9876512345"
    r2 = run(session, "Manjunath Gowda add karo", [{"intent": "ADD_CUSTOMER", "new_name": "Manjunath Gowda"}])
    assert not any(e["type"] == "customer_created" for e in r2.events)
    assert sum(1 for x in session.ledger.customers if x.name == "Manjunath Gowda") == 1


def test_rename_previous_customer(session):
    # STT misspelt a new person's name; shopkeeper opens the account, then fixes the spelling by voice
    run(session, "Baskur ko 200 udhaar", [{"intent": "TXN", "customer": "Baskur", "kind": "CREDIT", "amount_rupees": 200}])
    run(session, "haan", [{"intent": "YES"}])
    bad = session.ledger.find_by_name("Baskur")
    assert bad is not None
    r = run(session, "naam galat hai, Bhaskar likho",
            [{"intent": "RENAME_CUSTOMER", "customer_ref": "previous", "new_name": "bhaskar", "name_hi": "भास्कर"}])
    assert any(e["type"] == "customer_updated" for e in r.events)
    fixed = session.ledger.customer(bad.id)
    assert fixed.name == "Bhaskar" and fixed.name_hi == "भास्कर" and session.ledger.balance(bad.id) == 20000
    assert "भास्कर" in r.display


def test_new_customer_question_answered_with_corrected_name(session):
    r = run(session, "Bhaskar ko 150 udhaar",
            [{"intent": "TXN", "customer": "Bhaskar", "kind": "CREDIT", "amount_rupees": 150}])
    assert r.pending and r.pending["kind"] == "new_customer"
    run(session, "nahi, naam Bhaskar Rao hai", [{"intent": "ADD_CUSTOMER", "new_name": "Bhaskar Rao"}])
    c = session.ledger.find_by_name("Bhaskar Rao")
    assert c is not None and session.ledger.balance(c.id) == 15000
    assert session.ledger.find_by_name("Bhaskar") is None


def test_sales_summary_query(session):
    run(session, "Suresh ko 300 udhaar", [{"intent": "TXN", "customer": "Suresh", "kind": "CREDIT", "amount_rupees": 300}])
    r = run(session, "ನಮ್ಮ sales record ಇದೆ?", [{"intent": "QUERY", "query": "PERIOD_SUMMARY", "period": "today"}])
    assert "300" in r.display


def test_garbage_from_llm_is_harmless(session):
    clauses = to_clauses("blah", [{"intent": "DROP TABLE"}, "x", {"intent": "TXN", "amount_rupees": "abc"}],
                         session.ledger.customers)
    r = session.handle("blah", clauses=clauses)
    assert r is not None


def test_ledger_rename_and_remove(empty_ledger):
    L = empty_ledger
    c = L.add_customer("rames kumaar")
    L.update_customer(c.id, name="Ramesh Kumaran", phone="9876500099")
    assert L.customer(c.id).name == "Ramesh Kumaran" and L.customer(c.id).phone == "9876500099"
    assert any(a["action"] == "CUSTOMER_UPDATED" for a in L.audit_entries())
    L.remove_customer(c.id)
    assert c.id not in {x.id for x in L.customers}


def test_customer_rest_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.config import settings
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "k.db"))
    monkeypatch.setattr(settings, "voice_mode", "mock")
    from app.main import app
    with TestClient(app) as cl:
        r = cl.post("/api/customers", json={"name": "  rames  kumaar ", "phone": "98765 43210"})
        assert r.status_code == 200 and r.json()["name"] == "Rames Kumaar"
        cid_ = r.json()["id"]
        assert cl.post("/api/customers", json={"name": "Rames Kumaar"}).status_code == 409
        r = cl.patch(f"/api/customers/{cid_}", json={"name": "Ramesh Kumaran"})
        assert r.status_code == 200 and r.json()["name"] == "Ramesh Kumaran"
        assert cl.patch(f"/api/customers/{cid_}", json={"name": "Ramesh Kumar"}).status_code == 409   # seeded
        assert cl.patch(f"/api/customers/{cid_}", json={"phone": "123"}).status_code == 400
        assert cl.delete(f"/api/customers/{cid_}").status_code == 200
        assert cl.get(f"/api/customers/{cid_}").status_code == 404


def test_llm_cannot_swap_new_name_for_existing(session):
    # LLM "fixes" Aniket into an existing customer: we must still treat Aniket as a new person
    r = run(session, "Aniket ne 1500 ki shopping kari",
            [{"intent": "TXN", "customer": "Amit Patel", "heard_name": "Aniket", "kind": "CREDIT", "amount_rupees": 1500}])
    assert r.pending and r.pending["kind"] == "new_customer"
    run(session, "haan", [{"intent": "YES"}])
    a = session.ledger.find_by_name("Aniket")
    assert a and session.ledger.balance(a.id) == 150000
    assert session.ledger.balance(cid(session.ledger, "Amit Patel")) == 0


def test_llm_spelling_fix_of_same_person_is_kept(session):
    run(session, "Rames Kumaar ko 200 udhaar",
        [{"intent": "TXN", "customer": "Ramesh Kumar", "heard_name": "Rames Kumaar", "kind": "CREDIT", "amount_rupees": 200}])
    assert session.ledger.balance(cid(session.ledger, "Ramesh Kumar")) == 20000


def test_llm_unclear_direction_is_asked(session):
    r = run(session, "Suresh 500 credit",
            [{"intent": "TXN", "customer": "Suresh Yadav", "heard_name": "Suresh", "kind": None, "amount_rupees": 500}])
    assert r.pending and r.pending["kind"] == "need_kind"
    run(session, "aapko mila", [{"intent": "TXN", "kind": "PAYMENT"}])
    assert session.ledger.balance(cid(session.ledger, "Suresh Yadav")) == -50000
