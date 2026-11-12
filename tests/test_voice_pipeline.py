"""End-to-end voice loop against the protocol-faithful fake Gnani (tests/fake_gnani.py):
browser WS -> orchestrator -> Prisma adapter -> dialogue/ledger -> Timbre adapter -> browser."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from tests.fake_gnani import FakeGnani


@pytest.fixture(scope="module")
def fake():
    return FakeGnani().start()


@pytest.fixture
def client(fake, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "gnani_api_key", "test-key")
    monkeypatch.setattr(settings, "voice_mode", "gnani")
    monkeypatch.setattr(settings, "stt_url", fake.stt_url)
    monkeypatch.setattr(settings, "tts_url", fake.tts_url)
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "k.db"))
    from app.main import app
    with TestClient(app) as c:
        yield c


def recv_until(ws, pred, limit=200):
    got = []
    for _ in range(limit):
        m = ws.receive()
        if m.get("bytes") is not None:
            got.append(("audio", m["bytes"]))
            continue
        d = json.loads(m["text"])
        got.append(("json", d))
        if pred(d):
            return got
    raise AssertionError(f"never matched; got {[g[1] if g[0]=='json' else 'audio' for g in got]}")


def test_full_voice_turn(client, fake):
    fake.transcripts.append(("रमेश कुमार का तीन सौ चालीस उधार", "hi-IN"))
    with client.websocket_connect("/ws") as ws:
        ready = json.loads(ws.receive()["text"])
        assert ready["live"] is True
        ws.send_text(json.dumps({"type": "start", "mode": "ptt"}))
        got = recv_until(ws, lambda d: d.get("type") == "tts_end")
        greet = next(d for k, d in got if k == "json" and d.get("type") == "reply")
        assert "AI" in greet["display"]
        audio = b"".join(b for k, b in got if k == "audio")
        assert len(audio) == 16000 and audio[:4] != b"RIFF"       # header stripped, samples aligned

        ws.send_text(json.dumps({"type": "ptt_down"}))
        for _ in range(10):
            ws.send_bytes(b"\x00\x01" * 700)                          # odd sizes: adapter re-frames to 1024
        time.sleep(0.2)
        ws.send_text(json.dumps({"type": "ptt_up"}))
        got = recv_until(ws, lambda d: d.get("type") == "tts_end")
        types = [d.get("type") for k, d in got if k == "json"]
        assert "transcript" in types and "reply" in types and "metrics" in types
        reply = next(d for k, d in got if k == "json" and d.get("type") == "reply")
        txn = next(e for e in reply["events"] if e["type"] == "txn")["txn"]
        assert (txn["customer"], txn["kind"], txn["amount_paise"]) == ("Ramesh Kumar", "CREDIT", 34000)
        m = next(d for k, d in got if k == "json" and d.get("type") == "metrics")
        assert m["end_to_first_audio_ms"] < 2000
    assert fake.bad_frames == 0 and fake.commits >= 1
    h = fake.stt_headers[-1]
    assert h["model"] == "prisma-v3.0" and h["format"] == "transcribe" and "ramesh" in h.get("keyterms", "").lower()
    assert h["language_code"] == "indic-auto"       # list rejected -> fell back
    assert "lang_code" not in h                      # legacy duplicate header no longer sent
    tts = fake.tts_requests[-1]
    assert tts["model"] == "timbre-v3.0" and tts["language"] == "hi-IN"
    assert tts["audio_config"]["container"] == "raw" and tts["audio_config"]["sample_rate"] == 16000
    assert "तीन सौ चालीस" in tts["text"]            # amounts spoken as words


def test_barge_in_cancels_tts(client, fake):
    with client.websocket_connect("/ws") as ws:
        ws.receive()
        ws.send_text(json.dumps({"type": "start", "mode": "ptt"}))
        recv_until(ws, lambda d: d.get("type") == "tts_start")
        ws.send_text(json.dumps({"type": "ptt_down"}))            # shopkeeper talks over the agent
        got = recv_until(ws, lambda d: d.get("type") == "tts_cancel")
        assert got[-1][1]["reason"] == "ptt"


def test_typed_text_and_dashboard(client, fake):
    with client.websocket_connect("/ws") as ws:
        ws.receive()
        ws.send_text(json.dumps({"type": "text", "text": "Suresh ka 500 udhaar"}))
        got = recv_until(ws, lambda d: d.get("type") == "reply")
        assert "₹500" in got[-1][1]["display"]
    dash = client.get("/api/dashboard").json()
    assert dash["today_credit"] == 50000
    assert client.get("/api/health").json()["voice"] == "gnani"


def test_language_candidates():
    from app.gnani.stt import language_candidates
    assert language_candidates("hi-IN, kn-IN,en-IN") == ["hi-IN,kn-IN,en-IN", "indic-auto", "hi-IN"]
    assert language_candidates("indic-auto") == ["indic-auto"]
    assert language_candidates("kn-IN") == ["kn-IN", "indic-auto"]
