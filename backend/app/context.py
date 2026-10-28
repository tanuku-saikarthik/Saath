"""Next-call context: what tomorrow's call should know, sent to Bolna as user_data variables."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import Session, select

from .config import settings
from .models import Call, CallAnalysis, CallContext, Family, Medicine, Note, Parent, utcnow
from .mood import scored_calls, trend_stats

TONE_INSTRUCTIONS = {
    "warm": "Be warm and light. Share in her good news and keep the chat easy.",
    "gentle": (
        "She has seemed low recently. Speak slower and more gently, give her time, and ask one open question "
        "about how she is really feeling. Do not mention that she seemed low or that anything is being tracked."
    ),
}


# The Bolna welcome message is just "{opening}": the backend builds the whole greeting, so the first call
# can introduce Saath and later calls don't repeat it.
OPENINGS = {
    "te": {
        "intro": "నమస్తే {term}, నేను సాథ్ ని. {child} మీతో రోజూ మాట్లాడమని చెప్పారు. ఒక్క నిమిషం మాట్లాడవచ్చా?",
        "daily": "నమస్తే {term}! ఈ రోజు ఎలా గడిచింది?",
        "reminder": "నమస్తే {term}! మీ {medicine} వేసుకునే సమయం అయ్యింది. గుర్తు చేద్దామని ఫోన్ చేశాను.",
        "ask": "నమస్తే {term}! {child} మిమ్మల్ని ఒక విషయం అడగమన్నారు.",
        "inbound": "చెప్పండి {term}, ఎలా ఉన్నారు? ఏమైనా సహాయం కావాలా?",
        "callback": "{term}, మీరు ఇప్పుడే ఫోన్ చేశారు. అంతా బాగానే ఉందా?",
    },
    "hi": {
        "intro": "नमस्ते {term}, मैं साथ बोल रही हूँ। {child} ने कहा था कि मैं रोज़ आपसे बात करूँ। क्या एक मिनट बात कर सकते हैं?",
        "daily": "नमस्ते {term}! आज का दिन कैसा रहा?",
        "reminder": "नमस्ते {term}! आपकी {medicine} लेने का समय हो गया है। याद दिलाने के लिए फ़ोन किया।",
        "ask": "नमस्ते {term}! {child} ने आपसे एक बात पूछने को कहा है।",
        "inbound": "बताइए {term}, आप कैसी हैं? कुछ मदद चाहिए?",
        "callback": "{term}, आपने अभी फ़ोन किया था। सब ठीक है?",
    },
}


def opening_line(language: str, kind: str, child: str, medicine: str = "", term: str = "") -> str:
    lines = OPENINGS["hi" if language == "hi" else "te"]
    template = lines.get(kind) or lines["daily"]
    return template.format(child=child, term=term, medicine=medicine or ("दवा" if language == "hi" else "మందు"))


def today_so_far(session: Session, parent_id: int, ref: datetime | None = None) -> str:
    """What earlier calls today already covered, so the next call doesn't ask the same things again."""
    from .models import CallAnalysis as CA
    ref = ref or utcnow()
    since = ref - timedelta(hours=18)
    rows = session.exec(
        select(Call, CA).join(CA, CA.call_id == Call.id)
        .where(Call.parent_id == parent_id, Call.kind.in_(["ask", "reminder", "inbound", "callback", "daily", "retry"]),
               Call.scheduled_at >= since, Call.status == "completed").order_by(Call.scheduled_at)
    ).all()
    bits = []
    for c, a in rows:
        text = (a.summary or a.headline or "").replace("\n", " ").strip()
        if text:
            bits.append(f"{c.kind} call: {text[:220]}")
    return " | ".join(bits[-3:]) or "nothing yet today"


def build_context(session: Session, parent: Parent, ref: datetime | None = None) -> CallContext:
    ref = ref or utcnow()
    rows = scored_calls(session, parent.id, ref)
    moods = [a.mood_score for _, a in rows]
    stats = trend_stats(moods)

    tone = "warm"
    if moods and moods[-1] <= -0.2:
        tone = "gentle"
    elif stats["enough"] and stats["delta"] is not None and stats["delta"] <= -0.15:
        tone = "gentle"

    threads: list[str] = []
    for _, a in reversed(rows[-3:]):
        for t in a.open_threads:
            if t.lower() not in {x.lower() for x in threads}:
                threads.append(t)
    last = rows[-1][1] if rows else None
    meds_to_check = [m["name"] for m in (last.meds if last else []) if m.get("status") in ("missed", "unclear")]
    avoid = last.avoid_topics if last else []

    ctx = session.get(CallContext, parent.id) or CallContext(parent_id=parent.id)
    ctx.tone = tone
    ctx.open_threads = threads[:3]
    ctx.meds_to_check = meds_to_check
    ctx.avoid_topics = avoid[:3]
    ctx.last_note = last.headline if last else ""
    ctx.updated_at = utcnow()
    session.add(ctx)
    return ctx


def pending_notes(session: Session, parent_id: int) -> list[Note]:
    return list(session.exec(select(Note).where(Note.parent_id == parent_id, Note.call_id == None).order_by(Note.created_at)).all())  # noqa: E711


def child_message_text(notes: list[Note], kind: str = "daily") -> str:
    if not notes:
        return "none"
    parts = []
    for n in notes:
        t = n.text.strip()
        if getattr(n, "is_question", False):
            parts.append(t if kind == "ask" else f"(A question from them, ask it once and listen) {t}")
        else:
            parts.append(t.rstrip(".") + ".")
    return " ".join(parts)


def deliver_notes(session: Session, call: Call, analysis: CallAnalysis) -> None:
    """After a completed call: mark the child's messages delivered and attach her reply.

    A message counts as delivered only if the scoring LLM saw Saath pass it on; otherwise it stays
    pending for the next call.
    """
    if not call.note_ids or not analysis.message_delivered:
        return
    for i, note_id in enumerate(call.note_ids):
        note = session.get(Note, note_id)
        if note is None or note.call_id is not None:
            continue
        note.call_id = call.id
        note.delivered_at = call.scheduled_at
        note.reply = analysis.reply_to_child if i == len(call.note_ids) - 1 else ""
        session.add(note)


def prepare_call(session: Session, parent: Parent, call: Call) -> dict[str, str]:
    """user_data for a call that's about to start, recording which of the child's messages it carries."""
    # Reminder calls stay short: the child's messages wait for the evening call.
    notes = pending_notes(session, parent.id) if call.kind not in ("intro", "reminder") else []
    if call.kind == "ask":  # only the question(s) just asked; other messages wait for the evening call
        notes = [n for n in notes if n.is_question]
    call.note_ids = [n.id for n in notes]
    session.add(call)
    return user_data_for_call(session, parent, call.kind, notes, reminder_for=call.reminder_for)


def user_data_for_call(session: Session, parent: Parent, kind: str = "daily", notes: list[Note] | None = None,
                       reminder_for: str = "") -> dict[str, str]:
    """Flat string variables for the Bolna prompt ({{parent_name}}, {{open_threads}}, ...)."""
    ctx = session.get(CallContext, parent.id) or build_context(session, parent)
    family = session.get(Family, parent.family_id)
    meds = session.exec(select(Medicine).where(Medicine.parent_id == parent.id)).all()
    med_text = ", ".join(f"{m.name} ({m.timing})" if m.timing else m.name for m in meds) or "none"
    child = family.child_name if family else "your child"
    reminder = next((m for m in meds if m.name == reminder_for), None)
    return {
        "call_kind": kind,
        "opening": opening_line(parent.language, kind, child, reminder_for, parent.address_term),
        "reminder_medicine": reminder_for or "none",
        "reminder_timing": (reminder.timing if reminder and reminder.timing else "now") if reminder_for else "none",
        "today_so_far": today_so_far(session, parent.id),
        "parent_name": parent.name,
        "address_term": parent.address_term,
        "child_name": child,
        "child_message": child_message_text(notes or [], kind),
        "medicines": med_text,
        "meds_to_check": ", ".join(ctx.meds_to_check) or "none",
        "topics": ", ".join(parent.topics) or "her day",
        "open_threads": "; ".join(ctx.open_threads) or "nothing specific",
        "avoid_topics": ", ".join(ctx.avoid_topics) or "none",
        "tone_instruction": TONE_INSTRUCTIONS[ctx.tone],
        "last_call_note": ctx.last_note or "This is one of the first calls.",
        "timezone": settings.TIMEZONE,
    }
