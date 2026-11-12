"""Gnani Prisma v3.0 realtime STT over WebSocket (custom adapter).

Wire format per https://docs.gnani.ai/api/STT/stt-websocket :
  - wss://api.vachana.ai/stt/v3/stream, config in upgrade headers
  - client sends raw PCM16LE mono frames of exactly 1024 bytes at real-time cadence
  - client may send {"type":"commit"} to close the open utterance now (push-to-talk release)
  - client may send {"type":"update_settings", "bias": {"list": [...]}} (v3.0 keyterms)
  - server sends JSON: connected | speech_start | processing | transcript | error | settings_updated
We send both the documented header names and the older spellings used by Gnani's own
Pipecat/LiveKit plugins; the docs state the newer spelling wins when both are present.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Awaitable, Callable

import websockets

log = logging.getLogger("gnani.stt")

FRAME_BYTES = 1024          # 512 samples, 32 ms @ 16 kHz
EventCB = Callable[[dict], Awaitable[None]]


class PrismaStream:
    def __init__(self, *, api_key: str, url: str, model: str, languages: str, fmt: str,
                 sample_rate: int = 16000, keyterms: list[str] | None = None,
                 vad_threshold: str = "0.6", min_silence_ms: str = "500",
                 on_event: EventCB):
        self.api_key = api_key
        self.url = url
        self.model = model
        self.languages = languages
        self.fmt = fmt
        self.sample_rate = sample_rate
        self.keyterms = keyterms or []
        self.vad_threshold = vad_threshold
        self.min_silence_ms = min_silence_ms
        self.on_event = on_event
        self.ws = None
        self._recv_task: asyncio.Task | None = None
        self._buf = bytearray()
        self._connect_lock = asyncio.Lock()
        self._backlog: list[bytes] = []
        self.request_id: str | None = None
        self.connected_at = 0.0

    def _headers(self) -> dict[str, str]:
        rid = f"nc-{uuid.uuid4().hex[:12]}"
        self.request_id = rid
        h = {
            "x-api-key-id": self.api_key,
            "x-api-request-id": rid,
            "language_code": self.languages,
            "model": self.model,
            "format": self.fmt,
            "x-sample-rate": str(self.sample_rate),
            "x-idle-timeout-sec": "900",
            "x-vad-threshold": self.vad_threshold,
            "x-min-silence-ms": self.min_silence_ms,
            # legacy spellings (accepted by the server; documented ones win)
            "lang_code": self.languages,
            "x-model": self.model,
            "x-format": self.fmt,
        }
        if self.keyterms:
            # HTTP headers are ASCII: JSON-escape anything non-ASCII.
            h["keyterms"] = json.dumps(self.keyterms[:200], ensure_ascii=True)
        return h

    @property
    def is_open(self) -> bool:
        return self.ws is not None and self.ws.state.name == "OPEN"

    async def connect(self) -> None:
        async with self._connect_lock:
            if self.is_open:
                return
            t0 = time.perf_counter()
            self.ws = await websockets.connect(
                self.url, additional_headers=self._headers(), ping_interval=20, ping_timeout=20,
                close_timeout=3, max_size=None, open_timeout=8)
            first = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=8))
            if first.get("type") == "error":
                await self.ws.close()
                self.ws = None
                raise ConnectionError(f"Prisma rejected the session: {first.get('message')}")
            self.connected_at = time.monotonic()
            log.info("prisma connected in %.0f ms: %s", (time.perf_counter() - t0) * 1000,
                     json.dumps(first.get("config", first))[:300])
            await self.on_event({"type": "_connected", "config": first.get("config"),
                                 "connect_ms": round((time.perf_counter() - t0) * 1000)})
            self._recv_task = asyncio.create_task(self._recv_loop(), name="prisma-recv")
            backlog, self._backlog = self._backlog, []
        # Flush audio captured while connecting at ~2x real time (bursting degrades VAD).
        for i in range(0, len(backlog)):
            await self._send_frame(backlog[i])
            await asyncio.sleep(0.016)

    async def _recv_loop(self) -> None:
        ws = self.ws
        try:
            async for msg in ws:
                if isinstance(msg, bytes):
                    continue
                try:
                    data = json.loads(msg)
                except json.JSONDecodeError:
                    continue
                data["_rx"] = time.monotonic()
                await self.on_event(data)
        except websockets.ConnectionClosed as e:
            log.info("prisma closed: %s %s", e.code, e.reason)
            await self.on_event({"type": "_closed", "code": e.code, "reason": e.reason})
        except asyncio.CancelledError:
            raise
        except Exception as e:  # pragma: no cover
            log.exception("prisma recv error")
            await self.on_event({"type": "_closed", "code": -1, "reason": str(e)})
        finally:
            if self.ws is ws:
                self.ws = None

    async def send_audio(self, pcm: bytes) -> None:
        """Accept any chunk size; forward exact 1024-byte frames."""
        self._buf.extend(pcm)
        while len(self._buf) >= FRAME_BYTES:
            frame = bytes(self._buf[:FRAME_BYTES])
            del self._buf[:FRAME_BYTES]
            if not self.is_open:
                if len(self._backlog) < 160:          # keep up to ~5 s while (re)connecting
                    self._backlog.append(frame)
                continue
            await self._send_frame(frame)

    async def _send_frame(self, frame: bytes) -> None:
        try:
            await self.ws.send(frame)
        except Exception:
            self._backlog.append(frame)

    async def commit(self) -> None:
        """Push-to-talk released: pad the partial frame and close the utterance now."""
        if self._buf:
            self._buf.extend(b"\x00" * (FRAME_BYTES - len(self._buf)))
            await self.send_audio(b"")
        if self.is_open:
            await self.ws.send(json.dumps({"type": "commit"}))

    async def update_keyterms(self, terms: list[str]) -> None:
        self.keyterms = terms
        if self.is_open:
            await self.ws.send(json.dumps({"type": "update_settings", "bias": {"list": terms[:200]}}))

    async def close(self) -> None:
        if self._recv_task:
            self._recv_task.cancel()
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass
        self.ws = None
