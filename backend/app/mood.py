"""Mood memory and alert rules (PRD: starting values, tune on seeded data).

| Alert      | Fires when                                                                     | Cooldown |
| urgent     | any emergency mention                                                          | none     |
| drop       | mean of last 3 calls >= 0.3 below the median of the 14-day window before them, | 48 h     |
|            | and 2 of those 3 below that median; needs >= 5 calls in the window              |          |
| recurring  | loneliness or worry (score >= 0.4) in 3 of the last 5 calls                    | 48 h     |
| missed     | call and retry unanswered, or parent never spoke                               | 1 / day  |
| voice      | 2+ voice signals (pace, pauses, loudness, pitch movement) away from her usual   | 72 h     |
|            | for the last 3 calls; needs >= 5 earlier calls with the same kind of audio      |          |
| sos        | she called Saath herself (urgent instead, if she mentioned an emergency)       | none     |

Reminder calls (medicine) never count toward mood: they are short and functional.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean, median

from sqlmodel import Session, select

from .models import MOOD_KINDS, Alert, Call, CallAnalysis, Parent
from .pipeline import prosody

WINDOW_DAYS = 14
DROP_DELTA = 0.3
MIN_CALLS = 5
COOLDOWN = timedelta(hours=48)
RECURRING_LABELS = {"loneliness", "worry"}
RECURRING_MIN_SCORE = 0.4
VOICE_COOLDOWN = timedelta(hours=72)
VOICE_MIN_SIGNALS = 2


def scored_calls(session: Session, parent_id: int, until: datetime, days: int = WINDOW_DAYS) -> list[tuple[Call, CallAnalysis]]:
    since = until - timedelta(days=days)
    rows = session.exec(
        select(Call, CallAnalysis)
        .join(CallAnalysis, CallAnalysis.call_id == Call.id)
        .where(Call.parent_id == parent_id, Call.status == "completed", Call.kind.in_(MOOD_KINDS),
               Call.scheduled_at >= since, Call.scheduled_at <= until)
        .order_by(Call.scheduled_at)
    ).all()
    return list(rows)


def trend_stats(moods: list[float]) -> dict:
    """Baseline = median of the window before the last 3 calls; recent = mean of the last 3."""
    if len(moods) < MIN_CALLS:
        return {"enough": False, "baseline": None, "recent": None, "below": 0, "delta": None}
    last3, before = moods[-3:], moods[:-3]
    base = median(before)
    recent = mean(last3)
    return {
        "enough": True,
        "baseline": round(base, 3),
        "recent": round(recent, 3),
        "below": sum(m < base for m in last3),
        "delta": round(recent - base, 3),
    }


def _recent_alert(session: Session, parent_id: int, kind: str, ref: datetime, window: timedelta) -> bool:
    return session.exec(
        select(Alert).where(Alert.parent_id == parent_id, Alert.kind == kind, Alert.created_at >= ref - window, Alert.created_at <= ref)
    ).first() is not None


def talking_points(session: Session, parent_id: int, ref: datetime) -> list[str]:
    points: list[str] = []
    for _, a in reversed(scored_calls(session, parent_id, ref, days=7)):
        for item in a.open_threads + a.worries + a.topics:
            p = item.strip().rstrip(".")
            if p and p.lower() not in {x.lower() for x in points}:
                points.append(p)
        if len(points) >= 3:
            break
    return [p[0].upper() + p[1:] for p in points[:3]]


def evaluate_after_call(session: Session, parent: Parent, call: Call, analysis: CallAnalysis) -> list[Alert]:
    ref = call.scheduled_at
    name = parent.address_term
    alerts: list[Alert] = []
    mood_call = call.kind in MOOD_KINDS

    already_urgent = session.exec(select(Alert).where(Alert.call_id == call.id, Alert.kind == "urgent")).first() is not None
    if analysis.emergency and not already_urgent:  # a mid-call alert may have fired already
        alerts.append(Alert(
            parent_id=parent.id, call_id=call.id, kind="urgent", created_at=ref,
            title=f"{name} mentioned something urgent on tonight's call",
            reason=analysis.emergency_reason or "Possible emergency mentioned",
            talking_points=["Call her now", "If you can't reach her, ask a neighbour to check in"],
        ))

    if not mood_call:  # a medicine reminder: only the safety check applies
        for a in alerts:
            session.add(a)
        return alerts

    rows = scored_calls(session, parent.id, ref)
    moods = [a.mood_score for _, a in rows]
    stats = trend_stats(moods)
    if stats["enough"] and stats["delta"] <= -DROP_DELTA and stats["below"] >= 2:
        if not _recent_alert(session, parent.id, "drop", ref, COOLDOWN):
            mismatches = sum(a.mismatch for _, a in rows[-3:])
            extra = f" On {mismatches} of those calls she said she was fine but sounded low." if mismatches else ""
            alerts.append(Alert(
                parent_id=parent.id, call_id=call.id, kind="drop", created_at=ref,
                title=f"{name}'s mood has been lower for 3 calls",
                reason=f"Her last 3 calls averaged {stats['recent']:+.2f}, against her usual {stats['baseline']:+.2f}.{extra}",
                talking_points=talking_points(session, parent.id, ref),
            ))

    last5 = rows[-5:]
    hits = sum(any(e.get("label") in RECURRING_LABELS and e.get("score", 0) >= RECURRING_MIN_SCORE for e in a.text_emotions) for _, a in last5)
    if len(last5) >= 3 and hits >= 3 and not _recent_alert(session, parent.id, "recurring", ref, COOLDOWN):
        alerts.append(Alert(
            parent_id=parent.id, call_id=call.id, kind="recurring", created_at=ref,
            title=f"{name} has sounded lonely or worried several times",
            reason=f"Loneliness or worry came up in {hits} of her last {len(last5)} calls.",
            talking_points=talking_points(session, parent.id, ref),
        ))

    voice = voice_alert(session, parent, call, rows)
    if voice:
        alerts.append(voice)

    for a in alerts:
        session.add(a)
    return alerts


def voice_changes(rows: list[tuple[Call, CallAnalysis]]) -> dict:
    """Her last 3 calls against her earlier ones, only comparing like with like (same audio source)."""
    with_p = [a.prosody for _, a in rows if a.prosody]
    if not with_p:
        return {}
    src = with_p[-1].get("source")
    same = [p for p in with_p if p.get("source") == src]
    if len(same) < prosody.MIN_HISTORY + 3:
        return {}
    return prosody.compare(same[:-3], same[-3:])


def voice_alert(session: Session, parent: Parent, call: Call, rows: list[tuple[Call, CallAnalysis]]) -> Alert | None:
    changes = voice_changes(rows)
    words = prosody.describe(changes)
    if len(words) < VOICE_MIN_SIGNALS or _recent_alert(session, parent.id, "voice", call.scheduled_at, VOICE_COOLDOWN):
        return None
    listed = ", ".join(words[:-1]) + f" and {words[-1]}" if len(words) > 1 else words[0]
    return Alert(
        parent_id=parent.id, call_id=call.id, kind="voice", created_at=call.scheduled_at,
        title=f"{parent.address_term}'s voice has sounded different for 3 calls",
        reason=(
            f"Compared with her usual, she has been {listed}. This can be tiredness, a cold, poor sleep or "
            "feeling low. It is a reason to call, not a diagnosis."
        ),
        talking_points=["Ask how she has been sleeping", "Ask if she has been feeling unwell or tired"] + talking_points(session, parent.id, call.scheduled_at)[:1],
    )


def sos_alert(session: Session, parent: Parent, call: Call, headline: str = "", dropped: bool = False) -> Alert | None:
    """She called Saath herself. Skipped when that call already raised an urgent alert."""
    if session.exec(select(Alert).where(Alert.call_id == call.id, Alert.kind.in_(["urgent", "sos"]))).first():
        return None
    name = parent.address_term
    if dropped:
        reason = "The call ended before she said anything." + (" Saath is calling her back now." if call.kind == "inbound" else "")
        title = f"{name} called Saath"
    else:
        reason = headline or "She called Saath to talk."
        title = f"{name} called Saath herself"
    alert = Alert(
        parent_id=parent.id, call_id=call.id, kind="sos", created_at=call.scheduled_at, title=title, reason=reason,
        talking_points=["Give her a call when you can", "Ask what made her call"],
    )
    session.add(alert)
    return alert


def urgent_alert_now(session: Session, parent: Parent, call: Call | None, reason: str) -> Alert | None:
    """Raised mid-call (Bolna tool request or browser test call). One per call."""
    if call is not None:
        existing = session.exec(select(Alert).where(Alert.call_id == call.id, Alert.kind == "urgent")).first()
        if existing:
            return None
    alert = Alert(
        parent_id=parent.id, call_id=call.id if call else None, kind="urgent",
        title=f"{parent.address_term} needs you right now",
        reason=reason.strip() or "She mentioned something urgent during the call.",
        talking_points=["Call her now", "If you can't reach her, ask a neighbour to check in"],
    )
    session.add(alert)
    return alert


def missed_alert(session: Session, parent: Parent, call: Call) -> Alert | None:
    ref = call.scheduled_at
    day_start = ref.replace(hour=0, minute=0, second=0, microsecond=0)
    if _recent_alert(session, parent.id, "missed", ref, ref - day_start + timedelta(seconds=1)):
        return None
    alert = Alert(
        parent_id=parent.id, call_id=call.id, kind="missed", created_at=ref,
        title=f"{parent.address_term} missed tonight's check-in",
        reason=(
            f"Saath couldn't place tonight's call: {call.error}" if call.status == "failed" and call.error
            else "The call and the retry both went unanswered." if call.attempt > 1
            else "The call went unanswered or she didn't speak."
        ),
        talking_points=["Give her a quick call", "Check if her phone is charged and on"],
    )
    session.add(alert)
    return alert
