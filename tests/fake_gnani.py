"""A local stand-in for Gnani's two WebSocket APIs, built from the documented wire format.

It is NOT Gnani. It lets the automated tests exercise our adapters and orchestrator
(frame sizes, commit, event order, base64 TTS chunks with a WAV header, odd-length chunks,
barge-in) without network access. Real-API verification = scripts/smoke_*.py.
"""
from __future__ import annotations

import asyncio
import base64
import json
import struct
import threading
from collections import deque

from websockets.asyncio.server import serve


def wav_header(n_bytes: int, rate: int = 16000) -> bytes:
    return (b"RIFF" + struct.pack("<I", 36 + n_bytes) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", n_bytes))


class FakeGnani:
    def __init__(self):
        self.transcripts: deque[tuple[str, str]] = deque()   # (text, detected_language_code)
        self.stt_headers: list[dict] = []
        self.tts_requests: list[dict] = []
        self.bad_frames = 0
        self.accept_language_list = False   # live server (Nov 2026) rejects comma lists
        self.frames = 0
        self.commits = 0
        self.port = None
        self._loop = None
        self._ready = threading.Event()

    # ---------------------------------------------------------------- STT
    async def _stt(self, ws):
        h = {k.lower(): v for k, v in ws.request.headers.raw_items()}
        self.stt_headers.append(h)
        if not h.get("x-api-key-id"):
            await ws.close(1008, "no key")
            return
        lc = h.get("language_code") or ""
        if "," in lc and not self.accept_language_list:
            await ws.send(json.dumps({"type": "error", "message":
                f"Invalid language_code: exactly one locale is required (e.g. hi-IN). Received: {lc}. "
                "Use multi_lang_codes for parallel multi-locale transcription."}))
            await ws.close(1008, "bad language_code")
            return
        await ws.send(json.dumps({"type": "connected", "timestamp": "t",
                                  "config": {"sample_rate": int(h.get("x-sample-rate", 16000)), "chunk_size": 512,
                                             "language_code": h.get("language_code"), "format": h.get("format")},
                                  "request_id": h.get("x-api-request-id")}))
        seg = 0
        speaking = False
        async for msg in ws:
            if isinstance(msg, bytes):
                self.frames += 1
                if len(msg) != 1024:
                    self.bad_frames += 1
                if not speaking:
                    speaking = True
                    await ws.send(json.dumps({"type": "speech_start", "utterance_id": f"u{seg + 1}"}))
                continue
            data = json.loads(msg)
            if data.get("type") == "commit" and speaking:
                self.commits += 1
                speaking = False
                seg += 1
                await ws.send(json.dumps({"type": "processing"}))
                await asyncio.sleep(0.05)
                text, lang = self.transcripts.popleft() if self.transcripts else ("", "hi-IN")
                await ws.send(json.dumps({"type": "transcript", "text": text, "is_final": True,
                                          "segment_id": f"r-seg-{seg}", "segment_index": seg,
                                          "detected_language_code": lang, "latency": 50}))

    # ---------------------------------------------------------------- TTS
    async def _tts(self, ws):
        h = {k.lower(): v for k, v in ws.request.headers.raw_items()}
        if not h.get("x-api-key-id"):
            await ws.close(1008, "no key")
            return
        async for msg in ws:
            req = json.loads(msg)
            self.tts_requests.append(req)
            await ws.send(json.dumps({"type": "start", "request_id": "x"}))
            pcm = b"\x01\x00" * 8000                     # 0.5 s of audio
            chunks = [wav_header(len(pcm))[:20], wav_header(len(pcm))[20:] + pcm[:3001], pcm[3001:9000], pcm[9000:]]
            for i, c in enumerate(chunks):
                await ws.send(json.dumps({"type": "audio", "data": {"chunk_index": i, "audio": base64.b64encode(c).decode(),
                                                                    "is_final": False}}))
                await asyncio.sleep(0.02)
            await ws.send(json.dumps({"type": "complete", "data": {"chunk_index": len(chunks), "audio": "", "is_final": True}}))

    async def _handler(self, ws):
        from websockets.exceptions import ConnectionClosed
        try:
            if ws.request.path.startswith("/stt"):
                await self._stt(ws)
            else:
                await self._tts(ws)
        except ConnectionClosed:
            pass   # client aborted (barge-in) - expected

    def start(self):
        def run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            async def main():
                async with serve(self._handler, "127.0.0.1", 0) as server:
                    self.port = server.sockets[0].getsockname()[1]
                    self._ready.set()
                    await asyncio.Future()
            self._loop.run_until_complete(main())
        threading.Thread(target=run, daemon=True).start()
        self._ready.wait(5)
        return self

    @property
    def stt_url(self):
        return f"ws://127.0.0.1:{self.port}/stt/v3/stream"

    @property
    def tts_url(self):
        return f"ws://127.0.0.1:{self.port}/api/v1/tts"
