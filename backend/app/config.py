"""Settings loaded from saath/.env. Every key is optional so the app runs in mock mode with none set."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]  # saath/
BACKEND_ROOT = Path(__file__).resolve().parents[1]  # saath/backend/
load_dotenv(REPO_ROOT / ".env")


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


class Settings:
    # Bolna
    BOLNA_API_KEY = _get("BOLNA_API_KEY")
    BOLNA_BASE_URL = _get("BOLNA_BASE_URL", "https://api.bolna.ai")
    BOLNA_AGENT_ID_TE = _get("BOLNA_AGENT_ID_TE")
    BOLNA_AGENT_ID_HI = _get("BOLNA_AGENT_ID_HI")
    BOLNA_FROM_NUMBER = _get("BOLNA_FROM_NUMBER")  # optional; Bolna default number if empty
    # English agent that phones the child with an alert (prompts/agent_alert_en.md)
    BOLNA_AGENT_ID_ALERT = _get("BOLNA_AGENT_ID_ALERT")
    # The Bolna agent has a Transfer Call tool to the child's number: an urgent mid-call alert then
    # skips phoning the child separately, because Saath is connecting them directly.
    TRANSFER_ON_EMERGENCY = _get("TRANSFER_ON_EMERGENCY", "false").lower() == "true"
    # Shared secret for Bolna's mid-call tool requests (set the same value as the tool's api_token)
    TOOL_TOKEN = _get("TOOL_TOKEN")
    # The Bolna phone number she can call any time (linked to her language's agent for inbound calls,
    # with caller identification pointed at /webhooks/bolna/caller). Shown in the app to save in her phone.
    SOS_NUMBER = _get("SOS_NUMBER")
    # Ring her straight back when she calls Saath and the call drops before she says anything
    CALLBACK_ON_DROPPED = _get("CALLBACK_ON_DROPPED", "true").lower() == "true"

    # Optional: POST every alert, daily summary and weekly digest as JSON here
    # (connect it to WhatsApp, email or Slack with Make, Zapier or n8n)
    ALERT_WEBHOOK_URL = _get("ALERT_WEBHOOK_URL")

    # LLM (Sarvam-105B by default; any OpenAI-compatible endpoint works)
    SARVAM_API_KEY = _get("SARVAM_API_KEY")
    LLM_BASE_URL = _get("LLM_BASE_URL", "https://api.sarvam.ai/v1")
    LLM_MODEL = _get("LLM_MODEL", "sarvam-105b")
    LLM_API_KEY = _get("LLM_API_KEY") or _get("SARVAM_API_KEY")
    LLM_JSON_MODE = _get("LLM_JSON_MODE", "false").lower() == "true"

    # Browser test call (no Bolna): OpenAI listens, replies and speaks.
    OPENAI_BASE_URL = _get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    OPENAI_API_KEY = _get("OPENAI_API_KEY") or (
        _get("LLM_API_KEY") if "api.openai.com" in _get("LLM_BASE_URL") else ""
    )
    OPENAI_STT_MODEL = _get("OPENAI_STT_MODEL", "gpt-4o-mini-transcribe")
    OPENAI_TTS_MODEL = _get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts-2025-12-15")
    OPENAI_TTS_VOICE = _get("OPENAI_TTS_VOICE", "coral")

    # Voice emotion
    # hf = download from Hugging Face (usually faster from India), ms = ModelScope
    VOICE_HUB = _get("VOICE_HUB", "hf")
    VOICE_MODEL = _get("VOICE_MODEL") or ("emotion2vec/emotion2vec_plus_large" if VOICE_HUB == "hf" else "iic/emotion2vec_plus_large")
    # Which channel holds the parent in a two-channel recording (0 or 1). Confirm on day 1.
    PARENT_CHANNEL = int(_get("PARENT_CHANNEL", "1") or 1)

    # App
    PUBLIC_BASE_URL = _get("PUBLIC_BASE_URL")
    # Hosted demo: if the database is empty on start (free hosts wipe it on redeploy), load the labelled sample data.
    # Password for the family app. Empty = no login (fine on localhost). Set it on any public server.
    APP_PASSWORD = _get("APP_PASSWORD")
    AUTO_SEED = _get("AUTO_SEED", "false").lower() == "true"
    TEST_PHONE_NUMBER = _get("TEST_PHONE_NUMBER")
    DATABASE_URL = _get("DATABASE_URL", f"sqlite:///{BACKEND_ROOT / 'saath.db'}")
    DATA_DIR = Path(_get("DATA_DIR", str(BACKEND_ROOT / "data")))
    TIMEZONE = _get("TIMEZONE", "Asia/Kolkata")
    RETRY_MINUTES = int(_get("RETRY_MINUTES", "30") or 30)
    ENABLE_SCHEDULER = _get("ENABLE_SCHEDULER", "true").lower() == "true"
    # Comma-separated IPs; empty = accept all (ngrok rewrites client IPs during dev)
    WEBHOOK_IP_ALLOWLIST = [ip.strip() for ip in _get("WEBHOOK_IP_ALLOWLIST").split(",") if ip.strip()]
    CORS_ORIGINS = [o.strip() for o in _get("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if o.strip()]

    @property
    def bolna_enabled(self) -> bool:
        return bool(self.BOLNA_API_KEY)

    @property
    def llm_enabled(self) -> bool:
        local = any(h in self.LLM_BASE_URL for h in ("localhost", "127.0.0.1"))
        return bool(self.LLM_API_KEY) or local  # a local server (Ollama) needs no key

    def agent_id_for(self, language: str) -> str:
        return self.BOLNA_AGENT_ID_HI if language == "hi" else self.BOLNA_AGENT_ID_TE


settings = Settings()
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
(settings.DATA_DIR / "audio").mkdir(parents=True, exist_ok=True)
