"""Per-connection voice orchestrator (custom; no hosted agent platform in the loop).

Browser --(PCM16 16k frames + control JSON)--> here --> Prisma v3.0 (STT WS)
                                                    --> dialogue + ledger (deterministic)
                                                    --> Timbre v3.0 (TTS WS) --> PCM chunks --> browser
Modes
  ptt        audio flows only while the button is held; release -> {"type":"commit"} to Prisma,
             so end-of-speech is known instantly (no waiting for VAD silence). Transcripts from
             one press are merged into one turn.
  handsfree  audio always flows; Prisma's VAD segments turns; `speech_start` while the agent
             is talking = barge-in (stop TTS on server and client).
Latency metric = end of user speech (button release, or Prisma `processing` in hands-free)
-> first TTS audio chunk sent to the phone.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from . import llm
from .config import settings
from .dialogue import Reply, Session
from .gnani.stt import PrismaStream
from .gnani.tts import TimbreClient
from .ledger import Ledger
from .nlu.lexicon import WAKE
from .nlu.normalize import tokenize
from .nlu.parser import parse
from .nlu.romanize import pkey
from datetime import datetime, timedelta

from . import responses as R
from .timeutil import IST, now_ist, today_ist

log = logging.getLogger("voice")

KHATA_TERMS = ["Chotu", "udhaar", "udhar", "jama", "khata", "rupaye", "payment", "baaki", "hisaab", "parso",
               "udri", "saavira", "nooru", "ninne", "monne"]
WAKE_REQUIRED = os.getenv("HANDSFREE_WAKE", "1") == "1"   # hands-free: only "Chotu, ..." counts
FOLLOWUP_WINDOW_S = 8.0     # after a reply/question, answers don't need the wake word
TTS_LANG = {"hi": "hi-IN", "en": "en-IN", "kn": "kn-IN"}
PTT_FLUSH_TIMEOUT_S = 1.8
BARGE_IN_GRACE_S = 0.45      # ignore speech_start right after TTS starts (speaker echo)


def wake_config() -> dict | None:
    """Wake word is on only when a Picovoice key and a trained 'Hey Chotu' .ppn (Web/WASM) are present."""
    from .config import ROOT
    if not settings.picovoice_access_key:
        return None
    ppn = sorted((ROOT / "web" / "wake").glob("*.ppn"))
    if not ppn:
        return None
    return {"access_key": settings.picovoice_access_key, "keyword_url": f"/wake/{ppn[0].name}",
            "model_url": "/wake/porcupine_params.pv", "label": "Hey Chotu", "sensitivity": settings.wake_sensitivity}


def _confident(clauses) -> bool:
    """Rule parse that is safe to act on without the LLM: every clause a clean entry for one known customer."""
    if not clauses:
        return False
    if all((c.intent == "SET_ALARM" and c.alarm_at) or c.intent == "TIME" or
           (c.intent == "QUERY" and c.query in ("LIST_CUSTOMERS", "LIST_ENTRIES")) for c in clauses):
        return True
    for c in clauses:
        if c.intent != "TXN" or not c.amount or c.kind is None or not c.kind_explicit or c.confidence < 0.9:
            return False
        if c.mention is None or not c.mention.known or len(c.mention.candidates) != 1:
            return False
    return True


ONE_WORD_OK = {"haan", "han", "ha", "nahi", "nahin", "na", "ok", "okay", "yes", "no", "hmm", "ji", "theek", "sari", "howdu", "illa", "beda"}


class VoiceSession:
    def __init__(self, ws: WebSocket, ledger: Ledger):
        self.ws = ws
        self.ledger = ledger
        self.id = uuid.uuid4().hex[:10]
        self.dialogue = Session(self.id, ledger)
        self.live = settings.voice_mode == "gnani" and bool(settings.gnani_api_key)
        self.mode = "ptt"
        self.stt: PrismaStream | None = None
        self.tts: TimbreClient | None = None
        self._send_lock = asyncio.Lock()
        self._speak_task: asyncio.Task | None = None
        self._tts_started = 0.0
        self._connect_task: asyncio.Task | None = None
        # push-to-talk utterance state
        self.pressing = False
        self.released_at = 0.0
        self.utt_parts: list[str] = []
        self.utt_lang: str | None = None
        self.utt_ids: list[str] = []
        self.open_speech = False
        self.inflight = 0
        self._flush_task: asyncio.Task | None = None
        self._processing_at = 0.0
        self._last_reply_at = 0.0
        self.wake_turn = False
        self._llm_warned = False
        self.closed = False

    # ------------------------------------------------------------------ io
    async def send(self, obj: dict) -> None:
        if self.closed:
            return
        async with self._send_lock:
            try:
                await self.ws.send_text(json.dumps(obj, ensure_ascii=False, default=str))
            except Exception:
                self.closed = True

    async def send_audio(self, pcm: bytes) -> None:
        if self.closed:
            return
        async with self._send_lock:
            try:
                await self.ws.send_bytes(pcm)
            except Exception:
                self.closed = True

    async def run(self) -> None:
        await self.ws.accept()
        self._tick_task = asyncio.create_task(self._ticker(), name="reminders")
        await self.send({"type": "ready", "live": self.live, "session": self.id,
                         "mode_label": "Gnani Prisma v3.0 + Timbre v3.0" if self.live else "MOCK (typed text only, no Gnani)",
                         "wake": wake_config()})
        try:
            while True:
                msg = await self.ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    await self.on_audio(msg["bytes"])
                elif msg.get("text") is not None:
                    try:
                        data = json.loads(msg["text"])
                    except json.JSONDecodeError:
                        continue
                    await self.on_control(data)
        except WebSocketDisconnect:
            pass
        finally:
            self.closed = True
            await self.shutdown()

    async def shutdown(self) -> None:
        for t in (self._speak_task, self._flush_task, self._connect_task, getattr(self, "_tick_task", None)):
            if t and not t.done():
                t.cancel()
        if self.stt:
            await self.stt.close()
        if self.tts:
            await self.tts.abort()

    # ------------------------------------------------------------- control
    async def on_control(self, d: dict) -> None:
        typ = d.get("type")
        if typ == "start":
            self.mode = "handsfree" if d.get("mode") == "handsfree" else "ptt"
            self.dialogue.set_language(d.get("lang") or "")
            if self.live:
                await self._setup_gnani()
            await self.deliver(self.dialogue.greeting(), t_end=None)
        elif typ == "mode":
            new = "handsfree" if d.get("mode") == "handsfree" else "ptt"
            if new != self.mode:
                self.mode = new
                if self.live:
                    if self.stt:
                        await self.stt.close()
                    self.stt = None
                    await self._setup_gnani(tts=False)
        elif typ == "ptt_down":
            await self.barge_in("ptt")
            self.pressing = True
            self.wake_turn = bool(d.get("wake"))
            self.utt_parts, self.utt_ids, self.utt_lang = [], [], None
            if self._flush_task and not self._flush_task.done():
                self._flush_task.cancel()
            if self.live:
                self._ensure_stt()
        elif typ == "ptt_up":
            self.pressing = False
            self.released_at = time.monotonic()
            if self.live and self.stt:
                try:
                    await self.stt.commit()
                except Exception as e:
                    log.warning("commit failed: %s", e)
                self._flush_task = asyncio.create_task(self._flush_after_release())
        elif typ == "lang":
            # silent switch: no re-introduction, just recognise and reply in the new language
            old = self._stt_lang()
            self.dialogue.set_language(d.get("lang") or "auto")
            if self._stt_lang() != old:
                await self._restart_stt()
        elif typ == "interrupt":
            await self.barge_in("client")
        elif typ == "text":
            text = (d.get("text") or "").strip()
            if text:
                await self.send({"type": "transcript", "text": text, "lang": None, "typed": True})
                await self.process(text, None, t_end=time.monotonic(), ids=[])

    # --------------------------------------------------------------- gnani
    def _keyterms(self) -> list[str]:
        terms: list[str] = []
        for c in self.ledger.customers:
            for w in c.name.split():
                if w.lower() != "ji" and w not in terms:
                    terms.append(w)
        return terms[:180] + KHATA_TERMS

    async def _setup_gnani(self, tts: bool = True) -> None:
        silence = "1500" if self.mode == "ptt" else settings.min_silence_ms   # PTT ends turns via commit
        self.stt = PrismaStream(
            api_key=settings.gnani_api_key, url=settings.stt_url, model=settings.stt_model,
            languages=self._stt_lang(), fmt=settings.stt_format, keyterms=self._keyterms(),
            vad_threshold=settings.vad_threshold, min_silence_ms=silence, on_event=self.on_stt_event)
        if tts and self.tts is None:
            self.tts = TimbreClient(api_key=settings.gnani_api_key, url=settings.tts_url,
                                    model=settings.tts_model, voice=settings.tts_voice,
                                    sample_rate=settings.tts_sample_rate, speed=settings.tts_speed)
        self._ensure_stt()

    def _stt_lang(self) -> str:
        """A single locale recognises far better than auto-detect: use the shopkeeper's chosen language
        (Hindi/Kannada recognisers still take English words). Auto -> the configured setting."""
        return {"hi": "hi-IN", "kn": "kn-IN", "en": "en-IN"}.get(self.dialogue.preferred, settings.stt_languages)

    async def _restart_stt(self) -> None:
        if not self.live:
            return
        if self.stt:
            try:
                await self.stt.close()
            except Exception:
                pass
        self.stt = None
        await self._setup_gnani(tts=False)

    def _ensure_stt(self) -> None:
        if self.stt is None or self.stt.is_open:
            return
        if self._connect_task and not self._connect_task.done():
            return

        async def _go():
            try:
                await self.stt.connect()
            except Exception as e:
                log.error("prisma connect failed: %s", e)
                await self.send({"type": "error", "where": "stt", "message": f"Prisma connect failed: {e}"})
        self._connect_task = asyncio.create_task(_go())

    async def on_audio(self, pcm: bytes) -> None:
        if not self.live or self.stt is None:
            return
        if self.mode == "ptt" and not self.pressing:
            return
        if not self.stt.is_open:
            self._ensure_stt()
        await self.stt.send_audio(pcm)

    async def on_stt_event(self, d: dict) -> None:
        typ = d.get("type")
        if typ == "_connected":
            await self.send({"type": "stt_ready", "connect_ms": d.get("connect_ms"), "config": d.get("config")})
        elif typ == "speech_start":
            self.open_speech = True
            await self.send({"type": "stt_event", "event": "speech_start"})
            if self.mode == "handsfree" and self._speaking() and time.monotonic() - self._tts_started > BARGE_IN_GRACE_S:
                await self.barge_in("speech")
        elif typ == "processing":
            self.open_speech = False
            self.inflight += 1
            self._processing_at = time.monotonic()
            await self.send({"type": "stt_event", "event": "processing"})
        elif typ == "transcript":
            self.inflight = max(0, self.inflight - 1)
            self.open_speech = False
            text = (d.get("text") or "").strip()
            lang = d.get("detected_language_code")
            seg = d.get("segment_id") or d.get("utterance_id")
            await self.send({"type": "transcript", "text": text, "lang": lang, "segment_id": seg,
                             "stt_latency_ms": d.get("latency")})
            if not text:
                return
            if self.mode == "ptt":
                self.utt_parts.append(text)
                self.utt_ids.append(seg or "")
                self.utt_lang = self.utt_lang or lang
            else:
                addressed, rest = self._addressed(text)
                if not addressed:
                    await self.send({"type": "ignored", "text": text, "reason": "not addressed to Chotu"})
                    return
                await self.process(rest, lang, t_end=self._processing_at or time.monotonic(), ids=[seg] if seg else [])
        elif typ == "error":
            log.warning("prisma error: %s", d.get("message"))
            await self.send({"type": "error", "where": "stt", "message": d.get("message")})
        elif typ == "_closed":
            await self.send({"type": "stt_closed", "code": d.get("code"), "reason": d.get("reason")})

    def _addressed(self, text: str) -> tuple[bool, str]:
        """Hands-free in a busy shop: only "Chotu, ..." is a command, so counter chatter is ignored.
        Answers to a question just asked (or within a few seconds of a reply) need no wake word."""
        toks = tokenize(text)
        for i, tok in enumerate(toks[:3]):
            if pkey(tok) in WAKE:
                words = text.split()
                return True, " ".join(words[i + 1:]) if len(words) > i + 1 else ""
        if not WAKE_REQUIRED:
            return True, text
        if self.dialogue.pending is not None or time.monotonic() - self._last_reply_at < FOLLOWUP_WINDOW_S:
            return True, text
        return False, text

    async def _flush_after_release(self) -> None:
        """Wait until Prisma has finished every segment of this press, then run one turn."""
        deadline = self.released_at + PTT_FLUSH_TIMEOUT_S
        await asyncio.sleep(0.12)
        while time.monotonic() < deadline:
            if not self.open_speech and self.inflight == 0 and self.utt_parts:
                break
            if not self.open_speech and self.inflight == 0 and time.monotonic() - self.released_at > 1.2:
                break   # nothing was said
            await asyncio.sleep(0.03)
        parts, ids, lang = self.utt_parts, self.utt_ids, self.utt_lang
        self.utt_parts, self.utt_ids, self.utt_lang = [], [], None
        if not parts:
            await self.send({"type": "no_speech", "quiet": getattr(self, "wake_turn", False)})
            return
        if self.wake_turn:
            # "Hey Chotu, Suresh ka 500" said in one breath: drop the wake words from the command
            joined = " , ".join(parts)
            found, rest = self._addressed(joined)
            words = joined.split()
            if found and rest != joined and any(pkey(t) in WAKE for t in tokenize(" ".join(words[:3]))):
                parts = [rest] if rest.strip() else []
                if not parts:
                    await self.send({"type": "no_speech", "quiet": True})
                    return
        if getattr(self, "wake_turn", False) and self._is_noise(" ".join(parts)):
            await self.send({"type": "ignored", "text": " ".join(parts), "reason": "too short, probably background"})
            return
        await self.process(" , ".join(parts), lang, t_end=self.released_at, ids=ids)

    def _is_noise(self, text: str) -> bool:
        """Hands-free capture picked up a stray word from the shop floor? One word is only kept when it's
        an answer (haan/nahi), a number, or a question is pending."""
        words = [w for w in tokenize(text) if w.strip()]
        if len(words) >= 2 or self.dialogue.pending is not None:
            return False
        if not words:
            return True
        w = words[0].lower()
        return not (w in ONE_WORD_OK or any(ch.isdigit() for ch in w))

    # ------------------------------------------------------------- reminders
    async def _ticker(self) -> None:
        """While the app is open: fire due reminders and the daily closing summary (spoken + on screen)."""
        await asyncio.sleep(3)
        while not self.closed:
            try:
                await self.check_due()
            except Exception:
                log.exception("reminder tick failed")
            await asyncio.sleep(15)

    async def check_due(self, now: datetime | None = None) -> None:
        now = now or now_ist()
        for a in self.ledger.due_alarms(now):
            if not self.ledger.finish_alarm(a["id"]):
                continue                           # another open screen already fired it
            rep = self.dialogue.push_reply(R.simple("alarm_fire", self._push_lang(), x=a["text"]))
            rep.events.append({"type": "alarm", "alarm": a})
            await self.deliver(rep, None)
        if self.ledger.get_setting("closing_on", "1") != "1":
            return
        ct = self.ledger.get_setting("closing_time", settings.closing_time)
        h, m = (int(x) for x in ct.split(":"))
        due = datetime.combine(now.date(), datetime.min.time().replace(hour=h, minute=m), tzinfo=IST)
        if due <= now < due + timedelta(hours=3) and self.ledger.get_setting("closing_done") != now.date().isoformat():
            self.ledger.set_setting("closing_done", now.date().isoformat())
            d = now.date()
            rep = self.dialogue.push_reply(self.dialogue.summary_parts(d, d, "today", self._push_lang(), intro=True))
            rep.events.append({"type": "closing"})
            await self.deliver(rep, None)

    def _push_lang(self) -> str:
        d = self.dialogue
        return d.preferred if d.preferred != "auto" else d.lang

    # ------------------------------------------------------------- turns
    async def process(self, text: str, lang: str | None, t_end: float | None, ids: list[str]) -> None:
        t0 = time.monotonic()
        clauses = None
        if settings.llm_enabled and settings.nlu_mode == "llm":
            parsed = parse(text, self.ledger.customers, today_ist())
            if self.dialogue.pending is None and _confident(parsed.clauses):
                clauses = None            # fast path: a plain, unambiguous entry needs no LLM round trip
            else:
                # LLM understands free-form speech + context; rule parser if it fails or times out
                clauses = await llm.extract(text, self.ledger.customers, **self.dialogue.llm_context())
                if clauses is None and not self._llm_warned:
                    self._llm_warned = True
                    await self.send({"type": "notice", "text": "AI understanding is unavailable right now (check LLM_API_KEY); using basic mode."})
        else:
            parsed = parse(text, self.ledger.customers, today_ist())
            if parsed.clauses and all(c.intent == "UNKNOWN" for c in parsed.clauses) and settings.llm_enabled:
                clauses = await llm.extract(text, self.ledger.customers, **self.dialogue.llm_context())
        uid = "|".join(i for i in ids if i) or None
        reply = self.dialogue.handle(text, detected_lang=lang, utterance_id=uid, clauses=clauses)
        if reply is None:
            return
        try:
            self.ledger.log_transcript(self.id, "user", text, lang)
            self.ledger.log_transcript(self.id, "agent", reply.display, reply.lang)
        except Exception:  # never let logging break a turn
            log.exception("transcript log failed")
        await self.deliver(reply, t_end, brain_ms=round((time.monotonic() - t0) * 1000, 1))
        if any(e.get("type") in ("customer_created", "customer_updated") for e in reply.events) and self.stt:
            try:
                await self.stt.update_keyterms(self._keyterms())
            except Exception:
                pass

    async def deliver(self, reply: Reply, t_end: float | None, brain_ms: float | None = None) -> None:
        self._last_reply_at = time.monotonic()
        await self.send({"type": "reply", "display": reply.display, "speak": reply.speak, "lang": reply.lang,
                         "events": reply.events, "pending": reply.pending, "intents": reply.intents,
                         "nlu_ms": reply.nlu_ms, "brain_ms": brain_ms})
        if any(e.get("type") in ("txn", "customer_created") for e in reply.events):
            await self.send({"type": "dashboard_dirty"})
        if self.live and self.tts and reply.speak:
            await self.barge_in("new_reply")
            self._speak_task = asyncio.create_task(self._speak(reply.speak, reply.lang, t_end))

    def _speaking(self) -> bool:
        return self._speak_task is not None and not self._speak_task.done()

    async def _speak(self, text: str, lang: str, t_end: float | None) -> None:
        rid = uuid.uuid4().hex[:8]
        t_req = time.monotonic()
        first = True
        try:
            await self.send({"type": "tts_start", "id": rid, "sample_rate": settings.tts_sample_rate})
            self._tts_started = time.monotonic()
            async for pcm in self.tts.synthesize(text, TTS_LANG.get(lang, "hi-IN")):
                if first:
                    now = time.monotonic()
                    await self.send({"type": "metrics", "tts_first_chunk_ms": round((now - t_req) * 1000),
                                     "end_to_first_audio_ms": round((now - t_end) * 1000) if t_end else None})
                    first = False
                await self.send_audio(pcm)
            await self.send({"type": "tts_end", "id": rid})
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("tts failed: %s", e)
            await self.send({"type": "error", "where": "tts", "message": str(e)})
            if self.tts:
                await self.tts.abort()

    async def barge_in(self, reason: str) -> None:
        if self._speaking():
            self._speak_task.cancel()
            try:
                await self._speak_task
            except (asyncio.CancelledError, Exception):
                pass
            if self.tts:
                await self.tts.abort()
            await self.send({"type": "tts_cancel", "reason": reason})
