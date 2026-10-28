"""Turns a Bolna execution into a stored, scored call. Shared by the webhook and the polling fallback."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from .bolna import TERMINAL
from .config import settings
from .context import build_context, child_message_text, deliver_notes
from .db import session_scope
from .models import Alert, Call, CallAnalysis, Medicine, Note, Parent, utcnow
from .mood import evaluate_after_call, missed_alert, sos_alert
from .notify import notify_alert, send_daily_summary
from .pipeline.audio import download_recording
from .pipeline.fusion import fuse
from .pipeline.prosody import find_speaking_ms, measure_call
from .pipeline.text_scoring import parent_lines, score_transcript
from .pipeline.voice_scoring import score_recording

log = logging.getLogger(__name__)

CONSENT_YES = ["yes", "okay", "sure", "సరే", "అవును", "హా", "हाँ", "हां", "ठीक है", "जी"]


def _digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())[-10:]


def _find_call(session: Session, payload: dict[str, Any]) -> Call | None:
    exec_id = payload.get("id") or payload.get("execution_id")
    if exec_id:
        call = session.exec(select(Call).where(Call.bolna_execution_id == exec_id)).first()
        if call:
            return call
    # A call Saath didn't place: she called the Saath number (inbound), or someone dialled her from the
    # Bolna dashboard. Match the parent by her number.
    tel = payload.get("telephony_data") or {}
    inbound = is_inbound(payload)
    raw = (tel.get("from_number") or payload.get("user_number")) if inbound else (tel.get("to_number") or payload.get("user_number"))
    number = _digits(str(raw or ""))
    if not number:
        return None
    for parent in session.exec(select(Parent)).all():
        if _digits(parent.phone) == number:
            call = Call(parent_id=parent.id, bolna_execution_id=exec_id, status="in_progress", kind="inbound" if inbound else "daily")
            session.add(call)
            session.commit()
            session.refresh(call)
            return call
    return None


def is_inbound(payload: dict[str, Any]) -> bool:
    tel = payload.get("telephony_data") or {}
    return str(tel.get("call_type") or payload.get("call_type") or "").lower() == "inbound"


_lock = threading.Lock()  # webhook and poller may race on the same call


def handle_execution(payload: dict[str, Any]) -> tuple[str, int] | None:
    """Apply one Bolna execution update. Returns ("process"|"missed", call_id) when work remains."""
    with _lock:
        return _handle_execution(payload)


def _handle_execution(payload: dict[str, Any]) -> tuple[str, int] | None:
    status = str(payload.get("status") or "")
    with session_scope() as session:
        call = _find_call(session, payload)
        if call is None:
            log.info("Ignoring execution update for unknown call: %s", payload.get("id"))
            return None
        if call.status in ("processing", "completed", "missed"):
            return None  # already handled; Bolna sends several updates per call
        call.bolna_status = status
        if status not in TERMINAL:
            call.status = "in_progress"
            session.add(call)
            session.commit()
            return None

        call.duration_s = int(payload.get("conversation_duration") or 0)
        call.user_speaking_ms = find_speaking_ms(payload)
        if payload.get("transfer_call_data"):
            call.transferred = True  # Saath connected the parent to the child live
        transcript = str(payload.get("transcript") or "")
        if status == "completed" and parent_lines(transcript):
            call.transcript = transcript
            rec_url = (payload.get("telephony_data") or {}).get("recording_url")
            if rec_url:
                path = download_recording(rec_url, settings.DATA_DIR / "audio" / f"call_{call.id}")
                call.audio_path = str(path) if path else ""
            call.status = "processing"
            outcome = ("process", call.id)
        else:
            call.transcript = transcript
            call.status = "missed"
            outcome = ("missed", call.id)
        session.add(call)
        session.commit()
        return outcome


def run_outcome(outcome: tuple[str, int] | None) -> None:
    if not outcome:
        return
    kind, call_id = outcome
    if kind == "process":
        process_call(call_id)
    else:
        handle_missed(call_id)


def process_call(call_id: int) -> None:
    """Score a completed call, update mood memory and alerts, and plan the next call."""
    with session_scope() as session:
        call = session.get(Call, call_id)
        parent = session.get(Parent, call.parent_id)
        meds = [m.name for m in session.exec(select(Medicine).where(Medicine.parent_id == parent.id)).all()]
        notes = [n for n in (session.get(Note, i) for i in (call.note_ids or [])) if n is not None]
        call_kind = call.kind
        new_alert_ids: list[int] = []
        try:
            text, source = score_transcript(
                call.transcript, language=parent.language, address_term=parent.address_term, medicines=meds,
                call_kind=call.kind, child_message=child_message_text(notes),
            )
            voice = score_recording(Path(call.audio_path)) if call.audio_path else {"probs": {}, "valence": None, "source": "none", "segments": []}
            if call.bolna_status == "browser-test" and voice["source"] == "mixed":
                voice["source"] = "parent_channel"  # browser test calls record only the parent's turns
            mood, mismatch = fuse(text["valence"], voice["valence"], voice["source"], text["claimed_fine"])
            # How she spoke (pace, pauses, loudness, pitch). Reminder calls are too short to compare.
            spoken = " ".join(parent_lines(call.transcript))
            signals = {} if call.kind == "reminder" else measure_call(
                call.audio_path, spoken, call.user_speaking_ms, parent_only=call.bolna_status == "browser-test")

            analysis = session.get(CallAnalysis, call.id) or CallAnalysis(call_id=call.id)
            analysis.source = source
            analysis.text_emotions = text["emotions"]
            analysis.text_valence = text["valence"]
            analysis.arousal = text["arousal"]
            analysis.claimed_fine = text["claimed_fine"]
            analysis.evidence = text["evidence"]
            analysis.voice_probs = voice["probs"]
            analysis.voice_valence = voice["valence"]
            analysis.voice_source = voice["source"]
            analysis.voice_segments = voice["segments"]
            analysis.mood_score = mood
            analysis.mismatch = mismatch
            analysis.prosody = signals
            for key in ("meals", "meds", "worries", "health_mentions", "topics", "open_threads", "avoid_topics",
                        "emergency", "emergency_reason", "headline", "summary", "transcript_en",
                        "message_delivered", "reply_to_child", "consent"):
                setattr(analysis, key, text[key])
            session.add(analysis)

            call.status = "completed"
            call.processed_at = utcnow()
            session.add(call)
            session.flush()

            if call.kind == "intro":
                parent.consent_status = _consent_from(text["consent"], call.transcript, parent.consent_status)
                session.add(parent)

            deliver_notes(session, call, analysis)
            new_alerts = evaluate_after_call(session, parent, call, analysis)
            if call.kind == "inbound" and not analysis.emergency:
                sos = sos_alert(session, parent, call, headline=analysis.headline)
                if sos:
                    new_alerts.append(sos)
            build_context(session, parent, call.scheduled_at)
            session.commit()
            new_alert_ids = [a.id for a in new_alerts]
        except Exception as exc:
            log.exception("Processing call %s failed", call_id)
            session.rollback()
            call = session.get(Call, call_id)
            call.status = "failed"
            call.error = str(exc)[:500]
            session.add(call)
            session.commit()
            return
    for alert_id in new_alert_ids:
        notify_alert(alert_id)
    if call_kind not in ("intro", "reminder", "ask"):
        send_daily_summary(call_id)


def _consent_from(llm_answer: str, transcript: str, current: str) -> str:
    """Intro call: trust the scoring LLM's yes/no; fall back to keywords only when it's unclear."""
    if llm_answer == "yes":
        return "granted"
    if llm_answer == "no":
        return "declined"
    said = " ".join(parent_lines(transcript)).lower()
    return "granted" if any(w in said for w in CONSENT_YES) else current


def handle_missed(call_id: int) -> None:
    from .calls import schedule_retry  # avoid import cycle

    with session_scope() as session:
        call = session.get(Call, call_id)
        parent = session.get(Parent, call.parent_id)
        alert = None
        callback = False
        if call.kind in ("reminder", "ask"):
            pass  # a missed reminder or question isn't an alert; the evening call asks about medicines anyway
        elif call.kind == "inbound":
            # She called Saath and the call ended before she spoke: tell the family, and ring her back.
            callback = settings.CALLBACK_ON_DROPPED and settings.bolna_enabled and not call.is_seeded
            alert = sos_alert(session, parent, call, dropped=True)
            if alert and not callback:
                alert.reason = "The call ended before she said anything."
        elif call.kind == "callback":
            alert = Alert(
                parent_id=parent.id, call_id=call.id, kind="missed", created_at=call.scheduled_at,
                title=f"{parent.address_term} called Saath, then didn't answer the call back",
                reason="She called the Saath number, and when Saath rang her back she didn't pick up. Please call her.",
                talking_points=["Call her now", "If you can't reach her, ask a neighbour to check in"],
            )
            session.add(alert)
        elif call.kind != "intro" and call.attempt == 1 and not call.is_seeded:
            schedule_retry(parent.id)
        elif call.kind != "intro":
            alert = missed_alert(session, parent, call)
        session.commit()
        alert_id = alert.id if alert else None
        parent_id = parent.id
    if alert_id:
        notify_alert(alert_id)
    if callback:
        from .calls import call_back  # avoid import cycle

        call_back(parent_id)
