"""REST API for the family app, the Bolna webhook, and dev helpers."""
from __future__ import annotations

import re

from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from .calls import start_call
from .config import settings
from .db import get_session
from .models import ALERT_KINDS, MOOD_KINDS, Alert, Call, CallAnalysis, CallContext, Family, Medicine, Note, Parent, utcnow
from .mood import scored_calls, trend_stats
from .process import handle_execution, process_call, run_outcome
from .week import compute_week

router = APIRouter()
TZ = ZoneInfo(settings.TIMEZONE)
UTC = ZoneInfo("UTC")


def local(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(TZ).isoformat()


def parent_out(session: Session, p: Parent) -> dict[str, Any]:
    meds = session.exec(select(Medicine).where(Medicine.parent_id == p.id)).all()
    family = session.get(Family, p.family_id)
    return {
        "id": p.id, "name": p.name, "address_term": p.address_term, "phone": p.phone, "language": p.language,
        "call_time": p.call_time, "topics": p.topics, "consent_status": p.consent_status,
        "child_name": family.child_name if family else "",
        "child_phone": family.child_phone if family else "",
        "notify_kinds": (family.notify_kinds or []) if family else [],
        "neighbours": (family.neighbours or []) if family else [],
        "medicines": [{"id": m.id, "name": m.name, "timing": m.timing, "reminder_time": m.reminder_time} for m in meds],
    }


def note_out(n: Note) -> dict[str, Any]:
    return {
        "id": n.id, "text": n.text, "created_at": local(n.created_at), "call_id": n.call_id,
        "delivered_at": local(n.delivered_at), "reply": n.reply, "pending": n.call_id is None,
        "is_question": n.is_question,
    }


def analysis_out(a: Optional[CallAnalysis]) -> Optional[dict[str, Any]]:
    if a is None:
        return None
    return {
        "source": a.source, "text_emotions": a.text_emotions, "text_valence": a.text_valence, "arousal": a.arousal,
        "claimed_fine": a.claimed_fine, "evidence": a.evidence, "voice_probs": a.voice_probs,
        "voice_valence": a.voice_valence, "voice_source": a.voice_source, "voice_segments": a.voice_segments,
        "mood_score": a.mood_score, "mismatch": a.mismatch, "meals": a.meals, "meds": a.meds, "worries": a.worries,
        "health_mentions": a.health_mentions, "topics": a.topics, "open_threads": a.open_threads,
        "emergency": a.emergency, "emergency_reason": a.emergency_reason, "headline": a.headline,
        "summary": a.summary, "transcript_en": a.transcript_en,
        "message_delivered": a.message_delivered, "reply_to_child": a.reply_to_child, "prosody": a.prosody or {},
    }


def call_out(session: Session, c: Call, full: bool = False) -> dict[str, Any]:
    a = session.get(CallAnalysis, c.id)
    out: dict[str, Any] = {
        "id": c.id, "kind": c.kind, "attempt": c.attempt, "status": c.status, "scheduled_at": local(c.scheduled_at),
        "duration_s": c.duration_s, "is_seeded": c.is_seeded, "has_audio": bool(c.audio_path and Path(c.audio_path).exists()),
        "error": c.error, "headline": a.headline if a else "", "mood_score": a.mood_score if a else None,
        "mismatch": a.mismatch if a else False, "transferred": c.transferred, "reminder_for": c.reminder_for,
    }
    if full:
        out["transcript"] = c.transcript
        out["analysis"] = analysis_out(a)
        if out["analysis"] is not None:
            out["analysis"]["prosody_usual"] = prosody_usual(session, c, a)
        out["notes"] = [note_out(n) for n in session.exec(select(Note).where(Note.call_id == c.id)).all()]
    return out


def prosody_usual(session: Session, c: Call, a: CallAnalysis) -> dict[str, float]:
    """Her usual voice signals before this call (median of up to 14 days, same kind of audio)."""
    if not a.prosody or c.kind not in MOOD_KINDS:
        return {}
    src = a.prosody.get("source")
    earlier = [x.prosody for call, x in scored_calls(session, c.parent_id, c.scheduled_at)
               if call.id != c.id and x.prosody and x.prosody.get("source") == src]
    if len(earlier) < 5:
        return {}
    keys = ("pace_cps", "mean_pause_s", "loudness_db", "pitch_var_st")
    return {k: round(median(p[k] for p in earlier if k in p), 2) for k in keys if sum(k in p for p in earlier) >= 5}


def alert_out(a: Alert) -> dict[str, Any]:
    return {
        "id": a.id, "kind": a.kind, "title": a.title, "reason": a.reason, "talking_points": a.talking_points,
        "call_id": a.call_id, "created_at": local(a.created_at), "seen": a.seen_at is not None,
        "notified": a.notified, "notify_error": a.notify_error,
    }


def _parent_or_404(session: Session, parent_id: int) -> Parent:
    p = session.get(Parent, parent_id)
    if not p:
        raise HTTPException(404, "Parent not found")
    return p


# ---------- health ----------

@router.get("/api/health")
def health() -> dict[str, Any]:
    try:
        import funasr  # type: ignore  # noqa: F401
        voice = True
    except Exception:
        voice = False
    return {
        "ok": True, "bolna": settings.bolna_enabled, "llm": settings.llm_enabled, "llm_model": settings.LLM_MODEL,
        "voice_model_installed": voice, "agent_te": bool(settings.BOLNA_AGENT_ID_TE), "agent_hi": bool(settings.BOLNA_AGENT_ID_HI),
        "alert_calls": bool(settings.BOLNA_AGENT_ID_ALERT and settings.bolna_enabled),
        "alert_webhook": bool(settings.ALERT_WEBHOOK_URL), "transfer_on_emergency": settings.TRANSFER_ON_EMERGENCY,
        "test_call": bool(settings.OPENAI_API_KEY), "sos_number": settings.SOS_NUMBER,
    }


# ---------- parents ----------

class MedicineIn(BaseModel):
    name: str
    timing: str = ""
    reminder_time: str = ""  # HH:MM; empty = no reminder call


class ParentIn(BaseModel):
    name: str
    address_term: str
    phone: str
    language: str = "te"
    call_time: str = "19:00"
    topics: list[str] = []


class SetupIn(BaseModel):
    child_name: str
    child_phone: str = ""
    parent: ParentIn
    medicines: list[MedicineIn] = []
    place_intro_call: bool = True


@router.get("/api/parents")
def list_parents(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [parent_out(session, p) for p in session.exec(select(Parent)).all()]


@router.post("/api/parents")
def create_parent(body: SetupIn, session: Session = Depends(get_session)) -> dict[str, Any]:
    if body.parent.language not in ("te", "hi"):
        raise HTTPException(400, "language must be 'te' or 'hi'")
    family = Family(child_name=body.child_name, child_phone=body.child_phone)
    session.add(family)
    session.commit()
    session.refresh(family)
    parent = Parent(family_id=family.id, **body.parent.model_dump())
    session.add(parent)
    session.commit()
    session.refresh(parent)
    for m in body.medicines:
        session.add(Medicine(parent_id=parent.id, name=m.name, timing=m.timing))
    session.commit()
    intro = start_call(session, parent, "intro") if body.place_intro_call else None
    return {"parent": parent_out(session, parent), "intro_call": call_out(session, intro) if intro else None}


class ParentPatch(BaseModel):
    name: Optional[str] = None
    address_term: Optional[str] = None
    phone: Optional[str] = None
    language: Optional[str] = None
    call_time: Optional[str] = None
    topics: Optional[list[str]] = None
    consent_status: Optional[str] = None
    medicines: Optional[list[MedicineIn]] = None
    child_name: Optional[str] = None
    child_phone: Optional[str] = None
    notify_kinds: Optional[list[str]] = None
    neighbours: Optional[list[dict]] = None


@router.patch("/api/parents/{parent_id}")
def update_parent(parent_id: int, body: ParentPatch, session: Session = Depends(get_session)) -> dict[str, Any]:
    p = _parent_or_404(session, parent_id)
    data = body.model_dump(exclude_unset=True)
    meds = data.pop("medicines", None)
    family_fields = {k: data.pop(k) for k in ("child_name", "child_phone", "notify_kinds", "neighbours") if k in data}
    if "notify_kinds" in family_fields:
        family_fields["notify_kinds"] = [k for k in family_fields["notify_kinds"] if k in ALERT_KINDS]
    if "neighbours" in family_fields:
        clean = []
        for n in (family_fields["neighbours"] or [])[:5]:
            phone = re.sub(r"[^\d+]", "", str(n.get("phone", "")))
            if len(re.sub(r"\D", "", phone)) < 8:
                continue
            clean.append({"name": str(n.get("name", "")).strip()[:40] or "Neighbour", "phone": phone})
        family_fields["neighbours"] = clean
    for k, v in data.items():
        setattr(p, k, v)
    session.add(p)
    family = session.get(Family, p.family_id)
    if family and family_fields:
        for k, v in family_fields.items():
            setattr(family, k, v)
        session.add(family)
    if meds is not None:
        for m in session.exec(select(Medicine).where(Medicine.parent_id == p.id)).all():
            session.delete(m)
        for m in meds:
            session.add(Medicine(parent_id=p.id, name=m["name"], timing=m.get("timing", ""), reminder_time=m.get("reminder_time", "")))
    session.commit()
    return parent_out(session, p)


@router.get("/api/parents/{parent_id}/overview")
def overview(parent_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    p = _parent_or_404(session, parent_id)
    latest = session.exec(
        select(Call).where(Call.parent_id == p.id, Call.kind.in_(MOOD_KINDS)).order_by(Call.scheduled_at.desc())
    ).first()
    last_scored = session.exec(
        select(Call).join(CallAnalysis, CallAnalysis.call_id == Call.id)
        .where(Call.parent_id == p.id, Call.status == "completed", Call.kind.in_(MOOD_KINDS)).order_by(Call.scheduled_at.desc())
    ).first()
    rows = scored_calls(session, p.id, utcnow())
    stats = trend_stats([a.mood_score for _, a in rows])
    alerts = session.exec(select(Alert).where(Alert.parent_id == p.id, Alert.seen_at == None).order_by(Alert.created_at.desc())).all()  # noqa: E711
    ctx = session.get(CallContext, p.id)
    return {
        "parent": parent_out(session, p),
        "latest_call": call_out(session, latest, full=True) if latest else None,
        "last_scored_call": call_out(session, last_scored, full=True) if last_scored else None,
        "stats": stats,
        "unseen_alerts": [alert_out(a) for a in alerts],
        "next_call": {
            "tone": ctx.tone, "open_threads": ctx.open_threads, "meds_to_check": ctx.meds_to_check,
            "avoid_topics": ctx.avoid_topics,
        } if ctx else None,
    }


@router.get("/api/parents/{parent_id}/trend")
def trend(parent_id: int, days: int = 14, session: Session = Depends(get_session)) -> dict[str, Any]:
    p = _parent_or_404(session, parent_id)
    since = utcnow() - timedelta(days=days)
    calls = session.exec(
        select(Call).where(Call.parent_id == p.id, Call.kind.in_(MOOD_KINDS), Call.scheduled_at >= since).order_by(Call.scheduled_at)
    ).all()
    alerts = session.exec(select(Alert).where(Alert.parent_id == p.id, Alert.created_at >= since)).all()
    alerts_by_call: dict[int, list[str]] = {}
    for a in alerts:
        if a.call_id:
            alerts_by_call.setdefault(a.call_id, []).append(a.kind)
    points = []
    for c in calls:
        if c.kind == "daily" and c.status == "missed" and any(
            x.kind == "retry" and x.scheduled_at.date() == c.scheduled_at.date() for x in calls
        ):
            continue  # the retry row represents that evening
        a = session.get(CallAnalysis, c.id)
        points.append({
            "call_id": c.id, "date": local(c.scheduled_at), "status": c.status, "is_seeded": c.is_seeded,
            "mood": a.mood_score if a else None, "text_valence": a.text_valence if a else None,
            "voice_valence": a.voice_valence if a else None, "mismatch": a.mismatch if a else False,
            "alerts": alerts_by_call.get(c.id, []),
        })
    rows = scored_calls(session, p.id, utcnow())
    return {"points": points, "stats": trend_stats([a.mood_score for _, a in rows])}


@router.get("/api/parents/{parent_id}/calls")
def list_calls(parent_id: int, limit: int = 30, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    _parent_or_404(session, parent_id)
    calls = session.exec(select(Call).where(Call.parent_id == parent_id).order_by(Call.scheduled_at.desc()).limit(limit)).all()
    return [call_out(session, c) for c in calls]


@router.get("/api/calls/{call_id}")
def get_call(call_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    c = session.get(Call, call_id)
    if not c:
        raise HTTPException(404, "Call not found")
    return call_out(session, c, full=True)


@router.get("/api/calls/{call_id}/audio")
def call_audio(call_id: int, session: Session = Depends(get_session)) -> FileResponse:
    c = session.get(Call, call_id)
    if not c or not c.audio_path or not Path(c.audio_path).exists():
        raise HTTPException(404, "No audio for this call")
    return FileResponse(c.audio_path)


@router.get("/api/parents/{parent_id}/alerts")
def list_alerts(parent_id: int, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    _parent_or_404(session, parent_id)
    return [alert_out(a) for a in session.exec(select(Alert).where(Alert.parent_id == parent_id).order_by(Alert.created_at.desc())).all()]


@router.post("/api/alerts/{alert_id}/seen")
def mark_seen(alert_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    a = session.get(Alert, alert_id)
    if not a:
        raise HTTPException(404, "Alert not found")
    a.seen_at = utcnow()
    session.add(a)
    session.commit()
    return alert_out(a)


@router.post("/api/parents/{parent_id}/call-now")
def call_now(parent_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    p = _parent_or_404(session, parent_id)
    return call_out(session, start_call(session, p, "intro" if p.consent_status != "granted" else "daily"))


# ---------- messages from the child ----------

class NoteIn(BaseModel):
    text: str


@router.get("/api/parents/{parent_id}/notes")
def list_notes(parent_id: int, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    _parent_or_404(session, parent_id)
    notes = session.exec(select(Note).where(Note.parent_id == parent_id).order_by(Note.created_at.desc()).limit(20)).all()
    return [note_out(n) for n in notes]


@router.post("/api/parents/{parent_id}/notes")
def add_note(parent_id: int, body: NoteIn, session: Session = Depends(get_session)) -> dict[str, Any]:
    _parent_or_404(session, parent_id)
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Write a message first.")
    if len(text) > 300:
        raise HTTPException(400, "Keep it under 300 characters so Saath can pass it on naturally.")
    n = Note(parent_id=parent_id, text=text)
    session.add(n)
    session.commit()
    session.refresh(n)
    return note_out(n)


@router.post("/api/parents/{parent_id}/ask-now")
def ask_now(parent_id: int, body: NoteIn, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Type a question in English or Telugu/Hindi; Saath rings her now, asks it, and brings back her answer."""
    p = _parent_or_404(session, parent_id)
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Type your question first.")
    if len(text) > 300:
        raise HTTPException(400, "Keep it under 300 characters.")
    if p.consent_status != "granted":
        raise HTTPException(400, "She hasn't agreed to Saath's calls yet. Place the intro call first.")
    n = Note(parent_id=parent_id, text=text, is_question=True)
    session.add(n)
    session.commit()
    session.refresh(n)
    call = start_call(session, p, "ask")
    return {"note": note_out(n), "call": call_out(session, call)}


@router.delete("/api/notes/{note_id}")
def remove_note(note_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    n = session.get(Note, note_id)
    if not n:
        raise HTTPException(404, "Message not found")
    if n.call_id is not None:
        raise HTTPException(400, "This message was already passed on.")
    session.delete(n)
    session.commit()
    return {"ok": True}


# ---------- weekly digest ----------

@router.get("/api/parents/{parent_id}/week")
def week(parent_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    return compute_week(session, _parent_or_404(session, parent_id))


# ---------- Bolna webhook ----------

@router.post("/webhooks/bolna")
async def bolna_webhook(request: Request, background: BackgroundTasks) -> dict[str, Any]:
    if settings.WEBHOOK_IP_ALLOWLIST:
        ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")).split(",")[0].strip()
        if ip not in settings.WEBHOOK_IP_ALLOWLIST:
            raise HTTPException(403, "Unknown sender")
    payload = await request.json()
    outcome = handle_execution(payload)
    if outcome:
        background.add_task(run_outcome, outcome)  # reply 200 fast; score in the background
    return {"ok": True}


# ---------- dev helper: run the pipeline on a pasted transcript, no phone call ----------

class SimulateIn(BaseModel):
    parent_id: int
    transcript: str
    audio_path: str = ""


@router.post("/api/dev/simulate-call")
def simulate_call(body: SimulateIn, session: Session = Depends(get_session)) -> dict[str, Any]:
    p = _parent_or_404(session, body.parent_id)
    c = Call(parent_id=p.id, kind="daily", status="processing", transcript=body.transcript, audio_path=body.audio_path)
    session.add(c)
    session.commit()
    session.refresh(c)
    process_call(c.id)
    session.expire_all()
    return call_out(session, session.get(Call, c.id), full=True)
