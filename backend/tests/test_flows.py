"""Call flows: webhook idempotency, child messages, consent, failed calls, migration, LLM adaptation."""
import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import text

from app import bolna, calls, llm, process
from app.context import pending_notes, prepare_call
from app.db import engine, migrate
from app.models import Alert, Call, CallAnalysis, Family, Note, Parent, utcnow
from app.week import compute_week


def make_parent(session, consent="granted"):
    fam = Family(child_name="Karthik", child_phone="+919900000001")
    session.add(fam)
    session.commit()
    p = Parent(family_id=fam.id, name="Lakshmi", address_term="Amma", phone="+910000000000", consent_status=consent)
    session.add(p)
    session.commit()
    return p


TRANSCRIPT = "assistant: నమస్తే అమ్మా\nuser: బాగానే ఉంది నాయనా"


def test_webhook_updates_are_idempotent(session, monkeypatch):
    p = make_parent(session)
    c = Call(parent_id=p.id, bolna_execution_id="exec-1", status="queued")
    session.add(c)
    session.commit()
    monkeypatch.setattr(process, "download_recording", lambda *a, **k: None)
    assert process.handle_execution({"id": "exec-1", "status": "in-progress"}) is None
    assert process.handle_execution({"id": "exec-1", "status": "call-disconnected"}) is None  # not terminal
    first = process.handle_execution({"id": "exec-1", "status": "completed", "transcript": TRANSCRIPT})
    assert first == ("process", c.id)
    assert process.handle_execution({"id": "exec-1", "status": "completed", "transcript": TRANSCRIPT}) is None


def test_unanswered_call_is_missed(session):
    p = make_parent(session)
    c = Call(parent_id=p.id, bolna_execution_id="exec-2", status="queued")
    session.add(c)
    session.commit()
    assert process.handle_execution({"id": "exec-2", "status": "completed", "transcript": "assistant: Hello?\n"}) == ("missed", c.id)


def test_child_message_rides_with_call_and_reply_comes_back(session, monkeypatch):
    p = make_parent(session)
    session.add(Note(parent_id=p.id, text="Tell Amma I'll visit on Sunday"))
    session.commit()
    c = Call(parent_id=p.id, kind="daily", status="queued")
    session.add(c)
    session.flush()
    data = prepare_call(session, p, c)
    session.commit()
    assert "visit on Sunday" in data["child_message"] and c.note_ids

    def fake_score(*a, **k):
        assert "visit on Sunday" in k["child_message"]
        from app.pipeline.text_scoring import _normalise
        return _normalise({"valence": 0.4, "message_delivered": True, "reply_to_child": "Come soon", "headline": "h"}, []), "llm"

    monkeypatch.setattr(process, "score_transcript", fake_score)
    monkeypatch.setattr(process, "send_daily_summary", lambda *_: None)
    c.transcript, c.status = TRANSCRIPT, "processing"
    session.add(c)
    session.commit()
    process.process_call(c.id)
    session.expire_all()
    note = session.query(Note).one()
    assert note.call_id == c.id and note.reply == "Come soon"
    assert pending_notes(session, p.id) == []


def test_message_stays_pending_if_not_passed_on(session, monkeypatch):
    p = make_parent(session)
    session.add(Note(parent_id=p.id, text="Hello"))
    session.commit()
    c = Call(parent_id=p.id, kind="daily", status="processing", transcript=TRANSCRIPT)
    session.add(c)
    session.flush()
    prepare_call(session, p, c)
    session.commit()
    from app.pipeline.text_scoring import _normalise
    monkeypatch.setattr(process, "score_transcript", lambda *a, **k: (_normalise({"message_delivered": False}, []), "llm"))
    monkeypatch.setattr(process, "send_daily_summary", lambda *_: None)
    process.process_call(c.id)
    session.expire_all()
    assert len(pending_notes(session, p.id)) == 1


@pytest.mark.parametrize("answer,expected", [("yes", "granted"), ("no", "declined")])
def test_intro_consent_from_llm(session, monkeypatch, answer, expected):
    p = make_parent(session, consent="pending")
    c = Call(parent_id=p.id, kind="intro", status="processing", transcript=TRANSCRIPT)
    session.add(c)
    session.commit()
    from app.pipeline.text_scoring import _normalise
    monkeypatch.setattr(process, "score_transcript", lambda *a, **k: (_normalise({"consent": answer}, []), "llm"))
    process.process_call(c.id)
    session.expire_all()
    assert session.get(Parent, p.id).consent_status == expected


def test_scheduled_call_that_cannot_be_placed_retries_then_alerts(session, monkeypatch):
    p = make_parent(session)

    def boom(*a, **k):
        raise bolna.BolnaError("Bolna is down")

    monkeypatch.setattr(bolna, "place_call", boom)
    retried = []
    monkeypatch.setattr(calls, "schedule_retry", lambda pid, minutes=None: retried.append(pid))
    monkeypatch.setattr("app.calls.schedule_retry", lambda pid, minutes=None: retried.append(pid))
    first = calls.start_call(session, p, "daily", 1, scheduled=True)
    assert first.status == "failed" and retried == [p.id]
    second = calls.start_call(session, p, "retry", 2, scheduled=True)
    session.expire_all()
    alert = session.query(Alert).filter(Alert.call_id == second.id).one()
    assert alert.kind == "missed" and "Bolna is down" in alert.reason


def test_manual_call_failure_does_not_alert(session, monkeypatch):
    p = make_parent(session)
    monkeypatch.setattr(bolna, "place_call", lambda *a, **k: (_ for _ in ()).throw(bolna.BolnaError("no key")))
    calls.start_call(session, p, "daily", 1)  # "Call now"
    assert session.query(Alert).count() == 0


def test_migration_adds_missing_columns():
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS _probe (id INTEGER PRIMARY KEY)"))
        conn.execute(text("DROP TABLE _probe"))
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(alerts)"))]
        assert "notified" in cols
        conn.execute(text("ALTER TABLE alerts DROP COLUMN notified"))
    assert "alerts.notified" in migrate()
    with engine.begin() as conn:
        assert "notified" in [r[1] for r in conn.execute(text("PRAGMA table_info(alerts)"))]


def test_llm_adapts_to_rejected_parameters(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(sorted(body))
        for bad in ("max_tokens", "temperature"):
            if bad in body:
                return httpx.Response(400, json={"error": {"message": f"Unsupported parameter: '{bad}'"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    real_client = httpx.Client
    monkeypatch.setattr(llm.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(llm.settings, "LLM_API_KEY", "k")
    monkeypatch.setattr(llm.settings, "LLM_BASE_URL", "https://example.com/v1")
    assert llm.chat([{"role": "user", "content": "hi"}]) == "ok"
    assert "max_completion_tokens" in seen[-1] and "temperature" not in seen[-1]


def test_week_digest_counts(session):
    p = make_parent(session)
    for d, mood in ((1, -0.2), (2, -0.1), (3, 0.0)):
        c = Call(parent_id=p.id, status="completed", scheduled_at=utcnow() - timedelta(days=d))
        session.add(c)
        session.commit()
        session.add(CallAnalysis(call_id=c.id, mood_score=mood, mismatch=d == 1, meds=[], meals={"dinner": "skipped" if d == 2 else "eaten"}))
    for d in (9, 10):
        c = Call(parent_id=p.id, status="completed", scheduled_at=utcnow() - timedelta(days=d))
        session.add(c)
        session.commit()
        session.add(CallAnalysis(call_id=c.id, mood_score=0.4, meds=[], meals={}))
    session.commit()
    w = compute_week(session, p)
    assert w["reached"] == 3 and w["said_fine_sounded_low"] == 1 and w["meals_skipped"]["dinner"] == 1
    assert w["mood_delta"] < -0.15 and w["sentence"].startswith("A harder week")
