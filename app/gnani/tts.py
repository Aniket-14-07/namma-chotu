"""Gnani Timbre v3.0 realtime TTS over WebSocket (custom adapter).

Wire format per https://docs.gnani.ai/api/TTS/tts-websocket :
  - wss://api.vachana.ai/api/v1/tts with header X-API-Key-ID
  - client sends one JSON request {text, model, voice, language, speed, audio_config}
  - server replies {"type":"start"} then {"type":"audio","data":{"audio":<b64>,...}} ... then
    {"type":"complete"} (or {"type":"error"}); one request at a time per socket
  - no documented cancel message -> barge-in = close this socket, reopen for the next reply
Chunks may carry a WAV header (Gnani's Pipecat plugin strips them too) and may split a
16-bit sample across chunks; both are handled here so the browser only gets clean PCM.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from typing import AsyncIterator

import websockets

log = logging.getLogger("gnani.tts")
WAV_HEADER = 44


class _PcmCleaner:
    def __init__(self) -> None:
        self.rem = b""
        self.pending_hdr = b""

    def feed(self, data: bytes) -> bytes:
        if self.pending_hdr or data[:4] == b"RIFF":
            data = self.pending_hdr + data
            self.pending_hdr = b""
            if data[:4] == b"RIFF":
                if len(data) < WAV_HEADER:
                    self.pending_hdr = data
                    return b""
                # find the 'data' chunk (headers are usually exactly 44 bytes, but be safe)
                idx = data.find(b"data", 12)
                start = idx + 8 if 0 <= idx < 200 else WAV_HEADER
                data = data[start:]
        data = self.rem + data
        cut = len(data) - (len(data) % 2)
        self.rem = data[cut:]
        return data[:cut]


class TimbreClient:
    def __init__(self, *, api_key: str, url: str, model: str, voice: str, sample_rate: int = 16000,
                 speed: float = 1.0):
        self.api_key = api_key
        self.url = url
        self.model = model
        self.voice = voice
        self.sample_rate = sample_rate
        self.speed = speed
        self.ws = None
        self._lock = asyncio.Lock()

    @property
    def is_open(self) -> bool:
        return self.ws is not None and self.ws.state.name == "OPEN"

    async def connect(self) -> None:
        if self.is_open:
            return
        headers = {"X-API-Key-ID": self.api_key, "Content-Type": "application/json",
                   "X-API-Request-ID": f"nc-{uuid.uuid4().hex[:12]}"}
        self.ws = await websockets.connect(self.url, additional_headers=headers, ping_interval=20,
                                           ping_timeout=20, close_timeout=2, max_size=None, open_timeout=8)

    async def abort(self) -> None:
        """Barge-in: drop the in-flight synthesis. The next call reconnects."""
        ws, self.ws = self.ws, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass

    def payload(self, text: str, language: str) -> dict:
        return {
            "text": text,
            "model": self.model,
            "voice": self.voice,
            "language": language,
            "speed": self.speed,
            "audio_config": {"sample_rate": self.sample_rate, "num_channels": 1, "sample_width": 2,
                             "encoding": "linear_pcm", "container": "raw"},
        }

    async def synthesize(self, text: str, language: str) -> AsyncIterator[bytes]:
        """Yield clean PCM16LE mono chunks as they arrive."""
        async with self._lock:
            await self.connect()
            ws = self.ws
            cleaner = _PcmCleaner()
            t0 = time.perf_counter()
            await ws.send(json.dumps(self.payload(text, language), ensure_ascii=False))
            first = True
            try:
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=10)
                    if isinstance(msg, bytes):     # not documented, but tolerate binary audio
                        pcm = cleaner.feed(msg)
                        if pcm:
                            yield pcm
                        continue
                    data = json.loads(msg)
                    typ = data.get("type")
                    if typ == "audio" or typ == "complete":
                        inner = data.get("data") if isinstance(data.get("data"), dict) else data
                        b64 = inner.get("audio") or ""
                        if b64:
                            pcm = cleaner.feed(base64.b64decode(b64))
                            if pcm:
                                if first:
                                    log.info("timbre first audio in %.0f ms", (time.perf_counter() - t0) * 1000)
                                    first = False
                                yield pcm
                        if typ == "complete" or inner.get("is_final"):
                            return
                    elif typ == "error":
                        raise RuntimeError(f"Timbre error: {data.get('message')}")
            except websockets.ConnectionClosed:
                if self.ws is ws:
                    self.ws = None
                return
