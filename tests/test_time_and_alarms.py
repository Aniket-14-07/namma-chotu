"""Entry times, any-day summaries, shopkeeper reminders, closing time."""
from datetime import date, datetime, timedelta

from app.llm import to_clauses
from app.timeutil import IST
from tests.conftest import NOW, cid
from tests.test_scenarios import bal, say


def run(session, text, commands):
    return session.handle(text, clauses=to_clauses(text, commands, session.ledger.customers))


def test_entry_is_stamped_with_time(session):
    r = say(session, "Suresh ka 340 udhaar")
    t = [e for e in r.events if e["type"] == "txn"][0]["txn"]
    assert t["txn_time"] == NOW.strftime("%H:%M")


def test_spoken_time_is_not_an_amount(session):
    r = say(session, "Suresh ne shaam 5 baje 300 diye")
    assert bal(session.ledger, "Suresh Yadav") == -300
    t = [e for e in r.events if e["type"] == "txn"][0]["txn"]
    assert t["txn_time"] == "17:00"


def test_llm_time_and_date(session):
    r = run(session, "kal subah 10 baje Suresh ko 200 udhaar",
            [{"intent": "TXN", "customer": "Suresh Yadav", "heard_name": "Suresh", "kind": "CREDIT",
              "amount_rupees": 200, "days_ago": 1, "time": "10:00"}])
    t = [e for e in r.events if e["type"] == "txn"][0]["txn"]
    assert t["txn_time"] == "10:00" and t["txn_date"] == (NOW.date() - timedelta(days=1)).isoformat()


def test_last_payment_says_time(session):
    say(session, "Suresh ka 500 udhaar", "Suresh ne 200 diye")
    r = say(session, "Suresh ne last kab diya")
    assert "200" in r.display and ("शाम" in r.display or "PM" in r.display or "6" in r.display)


def test_summary_any_day(session):
    say(session, "Suresh ka 500 udhaar")
    r = run(session, "aaj ka hisaab", [{"intent": "QUERY", "query": "PERIOD_SUMMARY", "period": "today"}])
    assert "500" in r.display
    r = run(session, "10 November ka hisaab", [{"intent": "QUERY", "query": "PERIOD_SUMMARY", "date": "2026-11-10"}])
    assert "500" not in r.display.split("।")[0]


def test_dashboard_has_yesterday(session):
    run(session, "kal Suresh ko 200 udhaar",
        [{"intent": "TXN", "customer": "Suresh Yadav", "heard_name": "Suresh", "kind": "CREDIT", "amount_rupees": 200, "days_ago": 1}])
    say(session, "Suresh ne 50 diye")
    d = session.ledger.dashboard()
    assert d["yesterday"]["credit"] == 20000 and len(d["yesterday"]["entries"]) == 1
    assert d["today"]["payments"] == 5000


def test_alarm_by_voice_rule_parser(session):
    r = say(session, "mujhe shaam 7 baje yaad dilana Suresh se paise lene hain")
    assert any(e["type"] == "alarm_set" for e in r.events)
    a = session.ledger.alarms()[0]
    assert datetime.fromisoformat(a["due_at"]).hour == 19
    assert session.ledger.due_alarms(NOW) == []
    due = session.ledger.due_alarms(NOW.replace(hour=19, minute=1))
    assert len(due) == 1 and session.ledger.finish_alarm(due[0]["id"])
    assert not session.ledger.finish_alarm(due[0]["id"])          # fires once only


def test_alarm_by_llm_tomorrow(session):
    r = run(session, "kal subah 10 baje doodh wale ko call karna yaad dilana",
            [{"intent": "SET_ALARM", "alarm_at": "2026-11-12T10:00", "alarm_text": "doodh wale ko call karna"}])
    assert any(e["type"] == "alarm_set" for e in r.events)
    r = run(session, "subah 6 baje yaad dilana", [{"intent": "SET_ALARM", "alarm_at": "2026-11-11T06:00", "alarm_text": "x"}])
    assert not any(e["type"] == "alarm_set" for e in r.events)  # already past


def test_closing_time_and_summary(session):
    run(session, "roz raat 9 baje hisaab sunana", [{"intent": "CLOSING_TIME", "time": "21:00"}])
    assert session.ledger.get_setting("closing_time") == "21:00"
    say(session, "Suresh ka 500 udhaar")
    rep = session.push_reply(session.summary_parts(NOW.date(), NOW.date(), "today", "hi", intro=True), "hi")
    assert "500" in rep.display and "लेना" in rep.display


class _FakeWS:
    def __init__(self):
        self.out = []

    async def send_text(self, t):
        import json
        self.out.append(json.loads(t))

    async def send_bytes(self, b):
        pass


def test_ticker_fires_alarm_once_and_closing_summary(session, monkeypatch):
    import asyncio
    from app.config import settings
    from app.voice_session import VoiceSession
    monkeypatch.setattr(settings, "voice_mode", "mock")
    ws = _FakeWS()
    vs = VoiceSession(ws, session.ledger)
    vs.dialogue.handle("Suresh ka 500 udhaar")
    vs.ledger.add_alarm(NOW.replace(hour=19), "Suresh se paise lene hain")
    vs.ledger.set_setting("closing_time", "21:00")
    asyncio.run(vs.check_due(NOW.replace(hour=19, minute=0, second=5)))
    replies = [m for m in ws.out if m["type"] == "reply"]
    assert len(replies) == 1 and "Suresh se paise" in replies[0]["display"]
    asyncio.run(vs.check_due(NOW.replace(hour=19, minute=1)))
    assert len([m for m in ws.out if m["type"] == "reply"]) == 1          # not twice
    asyncio.run(vs.check_due(NOW.replace(hour=21, minute=0, second=10)))
    replies = [m for m in ws.out if m["type"] == "reply"]
    assert len(replies) == 2 and any(e["type"] == "closing" for e in replies[1]["events"])
    assert "500" in replies[1]["display"]
    asyncio.run(vs.check_due(NOW.replace(hour=21, minute=5)))
    assert len([m for m in ws.out if m["type"] == "reply"]) == 2          # once per day
