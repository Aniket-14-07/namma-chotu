"""FastAPI app: static mobile UI, REST for the dashboard, WebSocket for voice."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import ROOT, settings
from .db import Crypto, Database, load_or_create_key
from .ledger import Ledger
from .seed import seed
from .voice_session import VoiceSession

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("app")
WEB = ROOT / "web"


def build_ledger() -> Ledger:
    if settings.db_path.startswith(("postgres://", "postgresql://")) and not settings.ledger_key:
        raise RuntimeError("DATABASE_URL is set but LEDGER_KEY is empty: names would become unreadable after a restart")
    key_dir = Path(settings.db_path).parent if not settings.db_path.startswith("postgres") else Path("data")
    key = load_or_create_key(settings.ledger_key, key_dir / ".ledger_key")
    db = Database(settings.db_path, Crypto(key))
    ledger = Ledger(db)
    if os.getenv("SEED_DEMO", "1") == "1":
        seed(ledger)
    return ledger


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.ledger = build_ledger()
    live = settings.voice_mode == "gnani" and bool(settings.gnani_api_key)
    log.info("Namma Chotu up. voice=%s stt=%s tts=%s/%s langs=%s llm=%s", "GNANI" if live else "MOCK",
             settings.stt_model, settings.tts_model, settings.tts_voice, settings.stt_languages,
             "on" if settings.llm_enabled else "off")
    if not live:
        log.warning("MOCK MODE: no GNANI_API_KEY (or VOICE_MODE!=gnani). Typed text only; nothing is spoken.")
    yield


app = FastAPI(title="Namma Chotu", lifespan=lifespan)


def L() -> Ledger:
    return app.state.ledger


@app.get("/api/health")
def health():
    live = settings.voice_mode == "gnani" and bool(settings.gnani_api_key)
    return {"ok": True, "voice": "gnani" if live else "mock", "stt_model": settings.stt_model,
            "stt_languages": settings.stt_languages, "stt_format": settings.stt_format,
            "tts_model": settings.tts_model, "tts_voice": settings.tts_voice,
            "llm_fallback": settings.llm_enabled, "confirm_mode": settings.confirm_mode}


@app.get("/api/dashboard")
def dashboard():
    return L().dashboard()


@app.get("/api/customers")
def customers():
    led = L()
    rows = [led.customer_summary(c.id) for c in led.customers]
    return sorted(rows, key=lambda r: -r["balance"])


@app.get("/api/customers/{cid}")
def customer(cid: int):
    led = L()
    try:
        summary = led.customer_summary(cid)
    except KeyError:
        raise HTTPException(404)
    return {**summary, "transactions": led.customer_txns(cid)}


class NewCustomer(BaseModel):
    name: str
    phone: str | None = None
    reminder_opt_in: bool = False


def _phone(p: str | None) -> str | None:
    if p is None:
        return None
    digits = "".join(ch for ch in p if ch.isdigit())
    if digits and not 10 <= len(digits) <= 12:
        raise HTTPException(400, "phone must be 10 digits")
    return digits


@app.post("/api/customers")
def add_customer(body: NewCustomer):
    name = " ".join(body.name.split())
    if len(name) < 2:
        raise HTTPException(400, "name required")
    if L().find_by_name(name):
        raise HTTPException(409, f"{name} already has an account")
    c = L().add_customer(name, phone=_phone(body.phone) or None, reminder_opt_in=body.reminder_opt_in,
                         session_id="app")
    return L().customer_summary(c.id)


@app.get("/api/alarms")
def list_alarms():
    return L().alarms()


@app.delete("/api/alarms/{aid}")
def cancel_alarm(aid: int):
    if not L().finish_alarm(aid, "cancelled"):
        raise HTTPException(404)
    return {"ok": True}


class AppSettings(BaseModel):
    closing_time: str | None = None
    closing_on: bool | None = None


@app.get("/api/settings")
def get_settings():
    led = L()
    return {"closing_time": led.get_setting("closing_time", settings.closing_time),
            "closing_on": led.get_setting("closing_on", "1") == "1"}


@app.post("/api/settings")
def set_settings(body: AppSettings):
    led = L()
    if body.closing_time is not None:
        try:
            h, m = (int(x) for x in body.closing_time.split(":"))
            assert 0 <= h < 24 and 0 <= m < 60
        except Exception:
            raise HTTPException(400, "time must be HH:MM")
        led.set_setting("closing_time", f"{h:02d}:{m:02d}")
    if body.closing_on is not None:
        led.set_setting("closing_on", "1" if body.closing_on else "0")
    return get_settings()


@app.get("/api/day/{d}")
def day_report(d: str):
    from datetime import date
    try:
        return L().day_report(date.fromisoformat(d))
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")


class EditCustomer(BaseModel):
    name: str | None = None
    phone: str | None = None


@app.patch("/api/customers/{cid}")
def edit_customer(cid: int, body: EditCustomer):
    led = L()
    if cid not in {c.id for c in led.customers}:
        raise HTTPException(404)
    name = " ".join((body.name or "").split()) or None
    if name is not None and len(name) < 2:
        raise HTTPException(400, "name too short")
    if name:
        other = led.find_by_name(name)
        if other and other.id != cid:
            raise HTTPException(409, f"{name} already has an account")
    led.update_customer(cid, name=name, phone=_phone(body.phone), session_id="app")
    return led.customer_summary(cid)


@app.delete("/api/customers/{cid}")
def remove_customer(cid: int):
    led = L()
    if cid not in {c.id for c in led.customers}:
        raise HTTPException(404)
    try:
        led.remove_customer(cid, session_id="app")
    except ValueError:
        raise HTTPException(409, "Settle the balance to zero before removing this customer")
    return {"ok": True}


class OptIn(BaseModel):
    opt_in: bool


@app.post("/api/customers/{cid}/opt-in")
def set_opt_in(cid: int, body: OptIn):
    L().set_opt_in(cid, body.opt_in)
    return L().customer_summary(cid)


@app.get("/api/audit")
def audit(limit: int = 100):
    return L().audit_entries(limit)


@app.post("/api/admin/purge-transcripts")
def purge_transcripts():
    """Run after judging (Responsible-AI baseline: transcripts deleted after the demo)."""
    return {"deleted": L().purge_transcripts()}


@app.post("/api/admin/reset-demo")
def reset_demo():
    if os.getenv("DEMO_RESET_ENABLED", "1") != "1":
        raise HTTPException(403)
    led = L()
    with led.db.transaction() as db:
        for t in ("transactions", "audit_log", "transcripts", "reminders", "customers"):
            db.conn.execute(f"DELETE FROM {t}")
    led.reload_customers()
    seed(led)
    return {"ok": True}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await VoiceSession(ws, L()).run()


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
