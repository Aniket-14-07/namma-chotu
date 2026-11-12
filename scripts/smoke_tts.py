"""Smoke test #1: Timbre v3.0 over WebSocket. Writes smoke_tts.wav and prints first-chunk latency.

    python scripts/smoke_tts.py
    python scripts/smoke_tts.py "Ramesh ka teen sau chaalis udhaar" hi-IN
"""
import asyncio
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import settings  # noqa: E402
from app.gnani.tts import TimbreClient  # noqa: E402

TEXT = sys.argv[1] if len(sys.argv) > 1 else "रमेश कुमार के खाते में तीन सौ चालीस रुपये उधार लिखा। कुल बाकी एक हज़ार दो सौ चालीस रुपये।"
LANG = sys.argv[2] if len(sys.argv) > 2 else "hi-IN"


async def main():
    if not settings.gnani_api_key:
        sys.exit("GNANI_API_KEY missing in .env")
    c = TimbreClient(api_key=settings.gnani_api_key, url=settings.tts_url, model=settings.tts_model,
                     voice=settings.tts_voice, sample_rate=16000, speed=settings.tts_speed)
    t0 = time.perf_counter()
    await c.connect()
    print(f"connected in {(time.perf_counter() - t0) * 1000:.0f} ms  model={settings.tts_model} voice={settings.tts_voice}")
    pcm = bytearray()
    t1 = time.perf_counter()
    first = None
    async for chunk in c.synthesize(TEXT, LANG):
        if first is None:
            first = (time.perf_counter() - t1) * 1000
        pcm += chunk
    total = (time.perf_counter() - t1) * 1000
    out = Path("smoke_tts.wav")
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(bytes(pcm))
    print(f"first audio chunk: {first:.0f} ms | full synthesis: {total:.0f} ms | audio: {len(pcm) / 32000:.2f} s")
    print(f"wrote {out.resolve()}  <- play it and check the amount is read correctly")
    await c.abort()


asyncio.run(main())
