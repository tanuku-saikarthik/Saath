"""Browser test call: talk to Saath through the laptop mic, no Bolna or phone needed.

OpenAI does the three live jobs Bolna would do on a real call: hear (speech-to-text), decide what to
say (the same agent prompt as prompts/agent_<lang>.md), and speak (text-to-speech). When the call
ends, it goes through exactly the same pipeline as a phone call: scoring, mood memory, alerts and
next-call context. Only the parent's turns are recorded, so the voice signal gets clean
parent-only audio.
"""
from __future__ import annotations

import base64
import logging
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import select

from .config import BACKEND_ROOT, settings
from .context import prepare_call
from .db import session_scope
from .llm import LLMError, chat
from .models import Call, Family, Medicine, Parent
from .mood import urgent_alert_now
from .pipeline.emergency import keyword_emergency
from .process import process_call

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/test-call")
PROMPTS = BACKEND_ROOT / "prompts"
_sessions: dict[int, dict[str, Any]] = {}  # call_id -> {"system": str, "history": [...], "turns": [Path]}
_lock = threading.Lock()


class TestCallError(RuntimeError):
    pass


# ---------- prompt: same text as the Bolna agent ----------

def _blocks(md: str, heading: str) -> str:
    """First ``` block after a '## heading' line in the agent prompt file."""
    m = re.search(rf"## {re.escape(heading)}\s*\n+```\w*\n(.*?)```", md, re.S)
    if not m:
        raise TestCallError(f"'{heading}' block missing from the agent prompt file")
    return m.group(1).strip()


def _fill(template: str, data: dict[str, str]) -> str:
    return re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: data.get(m.group(1), ""), template)


def agent_prompts(parent: Parent, data: dict[str, str]) -> tuple[str, str]:
    md = (PROMPTS / f"agent_{'hi' if parent.language == 'hi' else 'te'}.md").read_text(encoding="utf-8")
    welcome = _fill(_blocks(md, "Welcome message"), data)
    system = _fill(_blocks(md, "System prompt"), data)
    system += (
        "\n\nThis is a phone-style voice call. Reply with 1 to 2 short spoken sentences only, "
        "in the call language, no lists or formatting."
    )
    return welcome, system


# ---------- OpenAI speech ----------

def _openai_headers() -> dict[str, str]:
    if not settings.OPENAI_API_KEY:
        raise TestCallError("The test call needs an OpenAI key: set LLM_API_KEY with LLM_BASE_URL=https://api.openai.com/v1, or OPENAI_API_KEY.")
    return {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}


def transcribe(audio: bytes, filename: str, language: str) -> str:
    files = {"file": (filename, audio, "application/octet-stream")}
    data = {"model": settings.OPENAI_STT_MODEL, "language": language}
    try:
        with httpx.Client(timeout=120) as c:
            r = c.post(f"{settings.OPENAI_BASE_URL}/audio/transcriptions", headers=_openai_headers(), files=files, data=data)
    except httpx.HTTPError as exc:
        raise TestCallError(f"Couldn't reach OpenAI for listening: {exc}") from exc
    if r.status_code >= 400:
        raise TestCallError(f"OpenAI transcription failed ({r.status_code}): {r.text[:300]}")
    return str(r.json().get("text", "")).strip()


def speak(text: str, language: str) -> str:
    """Returns base64 MP3."""
    lang = "Hindi" if language == "hi" else "Telugu"
    body: dict[str, Any] = {
        "model": settings.OPENAI_TTS_MODEL,
        "voice": settings.OPENAI_TTS_VOICE,
        "input": text,
        "response_format": "mp3",
        "instructions": f"Speak natural, warm, unhurried {lang}, like a caring younger relative talking to an elderly parent.",
    }
    try:
        with httpx.Client(timeout=120) as c:
            r = c.post(f"{settings.OPENAI_BASE_URL}/audio/speech", headers=_openai_headers(), json=body)
            if r.status_code == 400 and "instructions" in r.text.lower():  # older TTS models
                body.pop("instructions")
                r = c.post(f"{settings.OPENAI_BASE_URL}/audio/speech", headers=_openai_headers(), json=body)
    except httpx.HTTPError as exc:
        raise TestCallError(f"Couldn't reach OpenAI for speaking: {exc}") from exc
    if r.status_code >= 400:
        raise TestCallError(f"OpenAI speech failed ({r.status_code}): {r.text[:300]}")
    return base64.b64encode(r.content).decode()


# ---------- call flow ----------

def _turn_dir(call_id: int) -> Path:
    d = settings.DATA_DIR / "testcalls" / str(call_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _merge_parent_audio(paths: list[Path], dest: Path) -> str:
    """Join the parent's turns into one 16 kHz mono WAV. Needs ffmpeg; skipped (no voice signal) without it."""
    if not paths or not shutil.which("ffmpeg"):
        return ""
    inputs: list[str] = []
    for p in paths:
        inputs += ["-i", str(p)]
    filt = "".join(f"[{i}:a]" for i in range(len(paths))) + f"concat=n={len(paths)}:v=0:a=1[a]"
    res = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", filt, "-map", "[a]", "-ac", "1", "-ar", "16000", str(dest)],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        log.warning("Merging test-call audio failed: %s", res.stderr[:300])
        return ""
    return str(dest)


class StartIn(BaseModel):
    parent_id: int
    # daily: Saath calls her in the evening | reminder: a medicine reminder | inbound: she calls Saath (SOS line)
    kind: str = "daily"
    medicine: str = ""


@router.post("/start")
def start(body: StartIn) -> dict[str, Any]:
    with session_scope() as session:
        parent = session.get(Parent, body.parent_id)
        if not parent:
            raise HTTPException(404, "Parent not found")
        kind = "intro" if parent.consent_status != "granted" else body.kind if body.kind in ("daily", "reminder", "inbound") else "daily"
        reminder_for = ""
        if kind == "reminder":
            meds = session.exec(select(Medicine).where(Medicine.parent_id == parent.id)).all()
            pick = next((m for m in meds if m.name == body.medicine), None) or next((m for m in meds if m.reminder_time), None) or (meds[0] if meds else None)
            if pick is None:
                raise HTTPException(400, "Add a medicine in Profile first, so Saath has something to remind her about.")
            reminder_for = pick.name
        call = Call(parent_id=parent.id, kind=kind, status="in_progress", bolna_status="browser-test", reminder_for=reminder_for)
        session.add(call)
        session.flush()
        data = prepare_call(session, parent, call)  # carries any message from the child
        try:
            welcome, system = agent_prompts(parent, data)
            audio = speak(welcome, parent.language)
        except TestCallError as exc:
            session.rollback()
            raise HTTPException(400, str(exc)) from exc
        session.commit()
        session.refresh(call)
        family = session.get(Family, parent.family_id)
        with _lock:
            _sessions[call.id] = {
                "system": system, "language": parent.language, "parent_id": parent.id,
                "history": [{"role": "assistant", "content": welcome}], "turns": [], "kind": kind,
            }
        return {
            "call_id": call.id, "kind": kind, "reminder_for": reminder_for, "reply_text": welcome, "reply_audio": audio,
            "child_message": data["child_message"] if data["child_message"] != "none" else "",
            "child_phone": family.child_phone if family else "",
        }


@router.post("/{call_id}/turn")
async def turn(call_id: int, audio: UploadFile = File(...)) -> dict[str, Any]:
    with _lock:
        s = _sessions.get(call_id)
    if not s:
        raise HTTPException(404, "This test call has ended or the server restarted. Start a new one.")
    raw = await audio.read()
    if len(raw) < 1200:
        raise HTTPException(400, "That recording was too short. Hold the button while you speak.")
    ext = (audio.filename or "turn.webm").rsplit(".", 1)[-1][:5] or "webm"
    path = _turn_dir(call_id) / f"turn_{len(s['turns']):02d}.{ext}"
    path.write_bytes(raw)
    try:
        heard = transcribe(raw, path.name, s["language"])
    except TestCallError as exc:
        raise HTTPException(502, str(exc)) from exc
    if not heard:
        raise HTTPException(400, "Saath didn't catch any words. Try again a little closer to the mic.")
    s["turns"].append(path)
    s["history"].append({"role": "user", "content": heard})
    urgent = _mid_call_urgent(call_id, s["parent_id"], heard)
    try:
        reply = chat([{"role": "system", "content": s["system"]}, *s["history"]], max_tokens=1500, temperature=0.6).strip()
        reply_audio = speak(reply, s["language"])
    except (LLMError, TestCallError) as exc:
        s["history"].pop()
        s["turns"].pop()
        raise HTTPException(502, f"Saath couldn't reply: {exc}") from exc
    s["history"].append({"role": "assistant", "content": reply})
    return {"heard": heard, "reply_text": reply, "reply_audio": reply_audio, "urgent": urgent,
            "transfer": settings.TRANSFER_ON_EMERGENCY}


def _mid_call_urgent(call_id: int, parent_id: int, heard: str) -> str:
    """Same safety net as a phone call, raised the moment she says it. A test call records the alert
    but never phones anyone: the screen shows what would happen on a real call instead."""
    reason = keyword_emergency(f"user: {heard}")
    if not reason:
        return ""
    with session_scope() as session:
        parent = session.get(Parent, parent_id)
        call = session.get(Call, call_id)
        if parent and urgent_alert_now(session, parent, call, f"She said: \"{heard}\" ({reason})"):
            session.commit()
    return reason


@router.post("/{call_id}/end")
def end(call_id: int, background: BackgroundTasks) -> dict[str, Any]:
    with _lock:
        s = _sessions.pop(call_id, None)
    if not s:
        raise HTTPException(404, "This test call has already ended.")
    transcript = "\n".join(f"{'user' if m['role'] == 'user' else 'assistant'}: {m['content']}" for m in s["history"])
    with session_scope() as session:
        call = session.get(Call, call_id)
        call.transcript = transcript
        if not any(m["role"] == "user" for m in s["history"]):
            call.status = "missed"
            session.add(call)
            session.commit()
            return {"call_id": call_id, "status": "missed"}
        call.audio_path = _merge_parent_audio(s["turns"], _turn_dir(call_id) / "parent.wav")
        call.status = "processing"
        session.add(call)
        session.commit()
    background.add_task(process_call, call_id)
    return {"call_id": call_id, "status": "processing"}
