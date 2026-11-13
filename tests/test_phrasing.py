"""Many ways to say the same thing must land on the same side of the khata (rule parser, no LLM).
Balance > 0: the customer owes you ("lena hai"). Balance < 0: you owe the customer ("dena hai")."""
import pytest

from tests.test_scenarios import bal, say

HE_OWES = [
    "Suresh ne 500 ki shopping kari",
    "Suresh ka 500 udhaar bacha hai",
    "Suresh ko 500 dena hai",
    "Suresh se 500 lena hai",
    "Suresh 500 likh do",
    "Suresh ne 500 ka saman liya",
    "Suresh ko 500 ka maal diya",
    "Suresh ka 500 baaki hai",
    "Suresh ka 500 udhaar",
    "Suresh ko 500 loan diya",
    "Suresh owes 500",
    "Suresh bought for 500",
    "सुरेश ने 500 की shopping करी",
    "सुरेश को 500 देना है",
    "सुरेश का 500 उधार बचा है",
    "Suresh 500 kodbeku",
    "Suresh inda 500 barbeku",
    "Suresh ge 500 udri",
]

YOU_OWE = [
    "mujhe Suresh ko 500 dena hai",
    "maine Suresh ko 500 dene hain",
    "Suresh ne 500 advance diya",
    "Suresh ka 500 jama",
    "Suresh ne 500 diye",
    "Suresh ko 500 lena hai",
    "Suresh paid 500",
    "Suresh ne 500 GPay kiya",
    "I owe Suresh 500",
    "मुझे सुरेश को 500 देना है",
    "naanu Suresh ge 500 kodbeku",
]

# the shopkeeper's three examples, said about "this person" right after talking about Suresh
PRONOUN_HE_OWES = ["isne 500 ki shopping kari", "isko 500 paisa dena hai", "iska 500 udhaar bacha hai",
                   "इसने 500 की shopping करी", "इसको 500 पैसा देना है", "इसका 500 उधार बचा है"]


@pytest.mark.parametrize("utt", HE_OWES)
def test_he_owes_you(session, utt):
    say(session, utt)
    assert bal(session.ledger, "Suresh Yadav") == 500, utt


@pytest.mark.parametrize("utt", YOU_OWE)
def test_you_owe_him(session, utt):
    say(session, utt)
    assert bal(session.ledger, "Suresh Yadav") == -500, utt


@pytest.mark.parametrize("utt", PRONOUN_HE_OWES)
def test_pronoun_examples(session, utt):
    say(session, "Suresh ka hisaab batao")
    say(session, utt)
    assert bal(session.ledger, "Suresh Yadav") == 500, utt


@pytest.mark.parametrize("word,answer,expected", [
    ("credit", "udhaar", 500), ("credit", "jama", -500), ("debit", "udhaar", 500), ("credited", "jama", -500)])
def test_bare_credit_is_asked(session, word, answer, expected):
    r = say(session, f"Suresh 500 {word}")
    assert r.pending and r.pending["kind"] == "need_kind"
    assert bal(session.ledger, "Suresh Yadav") == 0          # nothing written before the answer
    say(session, answer)
    assert bal(session.ledger, "Suresh Yadav") == expected


def test_flip_is_confirmed_both_ways(session):
    say(session, "Suresh ka 300 udhaar")
    r = say(session, "Suresh ne 500 diye")
    assert r.pending and r.pending["kind"] == "overpay"
    assert bal(session.ledger, "Suresh Yadav") == 300
    say(session, "haan")
    assert bal(session.ledger, "Suresh Yadav") == -200
    r = say(session, "Suresh ka 1000 udhaar")                 # you owed him 200 -> now he owes you 800
    assert r.pending and r.pending["kind"] == "overpay"
    say(session, "nahi")
    assert bal(session.ledger, "Suresh Yadav") == -200


def test_settled_customer_paying_is_not_a_flip(session):
    say(session, "Suresh ne 500 advance diya")
    assert bal(session.ledger, "Suresh Yadav") == -500
    r = say(session, "Suresh ka hisaab")
    assert "500" in r.display
