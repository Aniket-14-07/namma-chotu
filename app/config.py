"""Runtime configuration from environment (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    gnani_api_key: str = field(default_factory=lambda: os.getenv("GNANI_API_KEY", ""))
    # "gnani" = real Prisma/Timbre. "mock" = typed text only, no audio (dev without key).
    voice_mode: str = field(default_factory=lambda: os.getenv("VOICE_MODE", "gnani"))

    stt_url: str = field(default_factory=lambda: os.getenv("GNANI_STT_URL", "wss://api.vachana.ai/stt/v3/stream"))
    stt_model: str = field(default_factory=lambda: os.getenv("GNANI_STT_MODEL", "prisma-v3.0"))
    # Up to 4 hints for prisma-v3.0, or "indic-auto".
    stt_languages: str = field(default_factory=lambda: os.getenv("GNANI_STT_LANGUAGES", "hi-IN,kn-IN,en-IN"))
    stt_format: str = field(default_factory=lambda: os.getenv("GNANI_STT_FORMAT", "transcribe"))
    # stricter speech detection ignores more background chatter (0..1, higher = needs clearer speech)
    vad_threshold: str = field(default_factory=lambda: os.getenv("GNANI_VAD_THRESHOLD", "0.75"))
    # "Hey Chotu" wake word (Picovoice Porcupine, runs on the phone). Put the .ppn in web/wake/.
    picovoice_access_key: str = field(default_factory=lambda: os.getenv("PICOVOICE_ACCESS_KEY", ""))
    wake_sensitivity: float = field(default_factory=lambda: float(os.getenv("WAKE_SENSITIVITY", "0.6")))
    min_silence_ms: str = field(default_factory=lambda: os.getenv("GNANI_MIN_SILENCE_MS", "400"))

    tts_url: str = field(default_factory=lambda: os.getenv("GNANI_TTS_URL", "wss://api.vachana.ai/api/v1/tts"))
    tts_model: str = field(default_factory=lambda: os.getenv("GNANI_TTS_MODEL", "timbre-v3.0"))
    tts_voice: str = field(default_factory=lambda: os.getenv("GNANI_TTS_VOICE", "Shivani"))
    tts_sample_rate: int = field(default_factory=lambda: int(os.getenv("GNANI_TTS_SAMPLE_RATE", "16000")))
    tts_speed: float = field(default_factory=lambda: float(os.getenv("GNANI_TTS_SPEED", "1.05")))

    # Optional LLM fallback (OpenAI-compatible chat completions). Empty = disabled.
    llm_base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", ""))
    llm_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", ""))
    llm_timeout_s: float = field(default_factory=lambda: float(os.getenv("LLM_TIMEOUT_S", "3")))
    # "llm" = LLM understands every turn (rule parser is the fallback). "rules" = rules first, LLM only if lost.
    closing_time: str = field(default_factory=lambda: os.getenv("CLOSING_TIME", "21:00"))   # daily summary, IST
    nlu_mode: str = field(default_factory=lambda: os.getenv("NLU_MODE", "llm"))

    # DATABASE_URL (Postgres) wins: data survives restarts and redeploys on free hosting.
    db_path: str = field(default_factory=lambda: os.getenv("DATABASE_URL") or os.getenv("DB_PATH", str(ROOT / "data" / "khata.db")))
    ledger_key: str = field(default_factory=lambda: os.getenv("LEDGER_KEY", ""))
    # "low" = ask before writing only when unsure (default). "always" = ask before every write.
    confirm_mode: str = field(default_factory=lambda: os.getenv("CONFIRM_MODE", "low"))
    greeting_language: str = field(default_factory=lambda: os.getenv("GREETING_LANGUAGE", "hi"))

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)


settings = Settings()
