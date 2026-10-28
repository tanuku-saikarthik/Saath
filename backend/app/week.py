"""Weekly digest: the last 7 evenings, compared with the 7 before. Computed from stored calls, no LLM."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from .config import settings
from .models import MOOD_KINDS, Alert, Call, CallAnalysis, Medicine, Note, Parent, utcnow
from .mood import scored_calls, voice_changes
from .pipeline.prosody import describe

TZ = ZoneInfo(settings.TIMEZONE)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _local_day(dt: datetime) -> str:
    return _aware(dt).astimezone(TZ).date().isoformat()


def _rows(session: Session, parent_id: int, since: datetime, until: datetime) -> list[tuple[Call, CallAnalysis | None]]:
    calls = session.exec(
        select(Call).where(Call.parent_id == parent_id, Call.kind.in_(MOOD_KINDS), Call.scheduled_at >= since, Call.scheduled_at < until).order_by(Call.scheduled_at)
    ).all()
    return [(c, session.get(CallAnalysis, c.id)) for c in calls]


def _mood_word(m: float | None) -> str:
    if m is None:
        return "no calls"
    return "bright" if m >= 0.35 else "steady" if m >= 0.15 else "low" if m >= -0.25 else "very low"


def compute_week(session: Session, parent: Parent, end: datetime | None = None) -> dict[str, Any]:
    end = _aware(end or utcnow())
    end_local = end.astimezone(TZ)
    # The week = the 7 local days ending today (or ending the day before `end` when it's early morning).
    last_day = end_local.date()
    days = [last_day - timedelta(days=i) for i in range(6, -1, -1)]
    start = datetime.combine(days[0], datetime.min.time(), TZ).astimezone(timezone.utc)
    until = datetime.combine(last_day + timedelta(days=1), datetime.min.time(), TZ).astimezone(timezone.utc)
    prev_start = start - timedelta(days=7)

    rows = _rows(session, parent.id, start, until)
    prev = [a for c, a in _rows(session, parent.id, prev_start, start) if a and c.status == "completed"]
    scored = [(c, a) for c, a in rows if a and c.status == "completed"]

    # One entry per evening: the scored call if there was one, else missed / no call.
    by_day: dict[str, list[tuple[Call, CallAnalysis | None]]] = defaultdict(list)
    for c, a in rows:
        by_day[_local_day(c.scheduled_at)].append((c, a))
    evenings = []
    for d in days:
        k = d.isoformat()
        items = by_day.get(k, [])
        best = next(((c, a) for c, a in reversed(items) if a and c.status == "completed"), None)
        if best:
            evenings.append({"date": k, "status": "completed", "call_id": best[0].id, "mood": best[1].mood_score, "mismatch": best[1].mismatch})
        elif any(c.status in ("missed", "failed") for c, _ in items):
            evenings.append({"date": k, "status": "missed", "call_id": items[-1][0].id, "mood": None, "mismatch": False})
        else:
            evenings.append({"date": k, "status": "none", "call_id": None, "mood": None, "mismatch": False})

    reached = sum(e["status"] == "completed" for e in evenings)
    missed = sum(e["status"] == "missed" for e in evenings)
    mood_now = round(mean(a.mood_score for _, a in scored), 3) if scored else None
    mood_prev = round(mean(a.mood_score for a in prev), 3) if prev else None
    delta = round(mood_now - mood_prev, 3) if mood_now is not None and mood_prev is not None else None
    mismatches = sum(a.mismatch for _, a in scored)

    # Medicines: of the evenings it came up, how often was it taken
    med_names = [m.name for m in session.exec(select(Medicine).where(Medicine.parent_id == parent.id)).all()]
    meds = []
    for name in med_names:
        statuses = [next((m["status"] for m in a.meds if m.get("name", "").lower() == name.lower()), "not_discussed") for _, a in scored]
        asked = [s for s in statuses if s != "not_discussed"]
        meds.append({
            "name": name, "asked": len(asked), "taken": asked.count("taken"),
            "missed": asked.count("missed"), "unclear": asked.count("unclear"),
        })

    meals = {k: sum((a.meals or {}).get(k) == "skipped" for _, a in scored) for k in ("breakfast", "lunch", "dinner")}

    # Medicine reminder calls: placed, answered, and confirmed taken on the call
    reminder_calls = session.exec(
        select(Call).where(Call.parent_id == parent.id, Call.kind == "reminder", Call.scheduled_at >= start, Call.scheduled_at < until)
    ).all()
    by_med: dict[str, dict[str, int]] = {}
    for c in reminder_calls:
        r = by_med.setdefault(c.reminder_for or "Medicine", {"placed": 0, "answered": 0, "taken": 0})
        r["placed"] += 1
        if c.status == "completed":
            r["answered"] += 1
            a = session.get(CallAnalysis, c.id)
            if a and any(m.get("status") == "taken" for m in a.meds):
                r["taken"] += 1
    reminders = [{"name": k, **v} for k, v in by_med.items()]

    called_saath = sum(c.kind == "inbound" for c, _ in rows)
    voice = describe(voice_changes(scored_calls(session, parent.id, until)))

    feel: dict[str, float] = defaultdict(float)
    for _, a in scored:
        for e in a.text_emotions:
            feel[e["label"]] += float(e.get("score", 0))
    top_feelings = [{"label": k, "score": round(v / len(scored), 3)} for k, v in sorted(feel.items(), key=lambda kv: -kv[1])[:4]] if scored else []

    topics: list[str] = []
    for _, a in reversed(scored):
        for t in a.topics:
            if t.lower() not in {x.lower() for x in topics}:
                topics.append(t)
    topics = topics[:8]

    alerts = session.exec(select(Alert).where(Alert.parent_id == parent.id, Alert.created_at >= start, Alert.created_at < until)).all()
    alert_counts: dict[str, int] = defaultdict(int)
    for al in alerts:
        alert_counts[al.kind] += 1

    notes = session.exec(select(Note).where(Note.parent_id == parent.id, Note.delivered_at != None, Note.delivered_at >= start, Note.delivered_at < until)).all()  # noqa: E711

    evening_calls = [(c, a) for c, a in scored if c.kind in ("daily", "retry")] or scored

    def pick(fn) -> dict[str, Any] | None:
        if not evening_calls:
            return None
        c, a = fn(evening_calls, key=lambda ca: ca[1].mood_score)
        return {"call_id": c.id, "date": _local_day(c.scheduled_at), "headline": a.headline, "mood": a.mood_score}

    name = parent.address_term
    if not scored:
        sentence = f"Saath didn't reach {name} this week."
    else:
        if delta is None:
            sentence = f"{name}'s mood this week was mostly {_mood_word(mood_now)}."
        elif delta <= -0.15:
            sentence = f"A harder week for {name} than the one before."
        elif delta >= 0.15:
            sentence = f"A brighter week for {name} than the one before."
        else:
            sentence = f"A steady week for {name}, close to the one before."
        sentence += f" Saath reached her on {reached} of 7 evenings."
        if mismatches:
            sentence += f" On {mismatches} {'call' if mismatches == 1 else 'calls'} she said she was fine but sounded low."

    return {
        "parent": {"id": parent.id, "name": parent.name, "address_term": name},
        "from": days[0].isoformat(),
        "to": last_day.isoformat(),
        "sentence": sentence,
        "evenings": evenings,
        "reached": reached,
        "missed": missed,
        "mood": mood_now,
        "mood_word": _mood_word(mood_now),
        "mood_prev": mood_prev,
        "mood_delta": delta,
        "said_fine_sounded_low": mismatches,
        "medicines": meds,
        "meals_skipped": meals,
        "reminders": reminders,
        "called_saath": called_saath,
        "voice_changes": voice,
        "top_feelings": top_feelings,
        "topics": topics,
        "alerts": dict(alert_counts),
        "brightest": pick(max),
        "lowest": pick(min),
        "messages": [{"text": n.text, "reply": n.reply, "delivered": _local_day(n.delivered_at)} for n in notes],
    }
