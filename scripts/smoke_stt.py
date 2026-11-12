"""Smoke test #2: Prisma v3.0 streaming. Streams a 16 kHz mono WAV at real-time pace,
sends {"type":"commit"} at the end, prints every server event and the commit->transcript time.

    python scripts/smoke_stt.py                 # uses smoke_tts.wav from smoke test #1
    python scripts/smoke_stt.py my_voice.wav    # record yourself: 16 kHz mono 16-bit WAV
                                                # (ffmpeg -i in.m4a -ac 1 -ar 16000 -sample_fmt s16 my_voice.wav)
"""
import asyncio
import json
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import settings  # noqa: E402
from app.gnani.stt import FRAME_BYTES, PrismaStream  # noqa: E402

PATH = sys.argv[1] if len(sys.argv) > 1 else "smoke_tts.wav"


async def main():
    if not settings.gnani_api_key:
        sys.exit("GNANI_API_KEY missing in .env")
    with wave.open(PATH, "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2, "need mono 16-bit"
        rate = w.getframerate()
        pcm = w.readframes(w.getnframes())
    print(f"{PATH}: {len(pcm) / 2 / rate:.2f} s @ {rate} Hz")
    done = asyncio.Event()
    marks = {}

    async def on_event(d):
        typ = d.get("type")
        now = time.perf_counter()
        if typ == "transcript":
            marks.setdefault("transcript", now)
            print(f"  TRANSCRIPT [{d.get('detected_language_code')}] {d.get('text')!r}  "
                  f"(server latency {d.get('latency')} ms, {d.get('audio_duration_ms')} ms audio)")
            done.set()
        elif typ == "_connected":
            print(f"  connected in {d.get('connect_ms')} ms, config: {json.dumps(d.get('config'), ensure_ascii=False)}")
        else:
            print(f"  event: {typ} {json.dumps({k: v for k, v in d.items() if k not in ('type', '_rx')}, ensure_ascii=False)[:200]}")

    s = PrismaStream(api_key=settings.gnani_api_key, url=settings.stt_url, model=settings.stt_model,
                     languages=settings.stt_languages, fmt=settings.stt_format, sample_rate=rate,
                     keyterms=["Ramesh", "Kumar", "udhaar", "jama"], vad_threshold=settings.vad_threshold,
                     min_silence_ms="1500", on_event=on_event)
    await s.connect()
    frame_s = FRAME_BYTES / 2 / rate
    for i in range(0, len(pcm), FRAME_BYTES):
        await s.send_audio(pcm[i:i + FRAME_BYTES])
        await asyncio.sleep(frame_s)
    t_commit = time.perf_counter()
    await s.commit()
    print("  -> commit sent")
    try:
        await asyncio.wait_for(done.wait(), timeout=6)
        print(f"commit -> transcript: {(marks['transcript'] - t_commit) * 1000:.0f} ms")
    except asyncio.TimeoutError:
        print("no transcript within 6 s after commit. Try GNANI_STT_LANGUAGES=indic-auto in .env, and send me the events above.")
    await s.close()


asyncio.run(main())
