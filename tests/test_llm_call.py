"""LLM transport recovery: retired model, JSON-mode refusal, bad key (no network; mocked HTTP)."""
import asyncio
import json

import httpx

from app import llm
from app.config import settings


def _setup(monkeypatch, handler, model="llama-3.3-70b-versatile"):
    monkeypatch.setattr(settings, "llm_api_key", "k")
    monkeypatch.setattr(settings, "llm_base_url", "https://api.groq.com/openai/v1")
    monkeypatch.setattr(settings, "llm_model", model)
    monkeypatch.setattr(llm, "_working_model", None)
    monkeypatch.setattr(llm, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _ok(cmds):
    return httpx.Response(200, json={"choices": [{"message": {"content": "```json\n" + json.dumps({"commands": cmds}) + "\n```"}}]})


def test_retired_model_falls_back(monkeypatch, session):
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append(body["model"])
        if body["model"] == "llama-3.3-70b-versatile":
            return httpx.Response(400, json={"error": {"message": "The model `llama-3.3-70b-versatile` has been decommissioned"}})
        return _ok([{"intent": "CHAT", "reply": "नमस्ते!"}])
    _setup(monkeypatch, handler)
    out = asyncio.run(llm.extract("hello", session.ledger.customers))
    assert out and out[0].intent == "CHAT" and out[0].reply == "नमस्ते!"
    assert seen[0] == "llama-3.3-70b-versatile" and seen[-1] == "openai/gpt-oss-20b"
    assert llm._working_model == "openai/gpt-oss-20b"


def test_json_mode_refused_retries_plain(monkeypatch, session):
    def handler(req):
        body = json.loads(req.content)
        if "response_format" in body:
            return httpx.Response(400, json={"error": {"message": "response_format not supported"}})
        return _ok([{"intent": "TIME"}])
    _setup(monkeypatch, handler, model="openai/gpt-oss-20b")
    assert asyncio.run(llm.extract("time?", session.ledger.customers)) is not None


def test_bad_key_reports(monkeypatch, session):
    _setup(monkeypatch, lambda req: httpx.Response(401, json={"error": "invalid api key"}))
    assert asyncio.run(llm.extract("x", session.ledger.customers)) is None
    assert "rejected" in llm.last_error
