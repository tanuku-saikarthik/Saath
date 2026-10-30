"""SOS line (inbound calls), medicine reminder calls, and voice wellness signals."""
import wave
from datetime import timedelta
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from sqlmodel import select

from app import calls, process
from app.config import settings
from app.main import app
from app.models import Alert, Call, CallAnalysis, Family, Medicine, Parent, utcnow
from app.mood import evaluate_after_call, scored_calls
from app.pipeline import prosody
from app.week import compute_week

TRANSCRIPT = "assistant: నమస్తే అమ్మా\nuser: బాగానే ఉంది నాయనా"


def make_parent(session):
    fam = Family(child_name="Karthik", child_phone="+919900000001", notify_kinds=["urgent", "sos", "voice", "missed"])
    session.add(fam)
    session.commit()
    p = Parent(family_id=fam.id, name="Lakshmi", address_term="Amma", phone="+91 98480 12345", consent_status="granted")
    session.add(p)
    session.commit()
    return p


# ---------- voice wellness signals ----------

def _tone_file(path: Path, gap_s: float, amp: float, vibrato: float) -> Path:
    rate = 16000
    t = np.arange(int(rate * 1.2)) / rate
    parts = []
    for i in range(10):
        f = 180 + vibrato * np.sin(2 * np.pi * 0.7 * i)
        parts.append(amp * np.sin(2 * np.pi * f * t))
        parts.append(np.random.default_rng(i).normal(0, 0.002, int(rate * gap_s)))
    x = np.concatenate(parts)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    return path


def test_prosody_measures_pauses_loudness_and_pitch(tmp_path):
    usual = prosody.analyse_audio(_tone_file(tmp_path / "a.wav", 0.4, 0.3, 20), "బాగానే ఉన్నాను")
    low = prosody.analyse_audio(_tone_file(tmp_path / "b.wav", 1.1, 0.12, 4), "బాగానే ఉన్నాను")
    assert low["mean_pause_s"] > usual["mean_pause_s"] * 2
    assert low["loudness_db"] < usual["loudness_db"] - 4
    assert low["pitch_var_st"] < usual["pitch_var_st"] * 0.75
    words = prosody.describe(prosody.compare([usual] * 6, [low] * 3))
    assert {"pausing longer", "speaking more quietly", "speaking in a flatter voice"} <= set(words)


def test_spoken_chars_ignores_vowel_signs():
    assert prosody.spoken_chars("నమస్తే") < len("నమస్తే")
    assert prosody.spoken_chars("hello, ok!") == 7


def test_speaking_ms_found_anywhere_in_payload():
    assert prosody.find_speaking_ms({"a": {"interruption_stats": {"user_speaking_ms": 41000}}}) == 41000
    assert prosody.find_speaking_ms({"a": [1, 2]}) == 0


def _scored(session, p, days_ago, signals, kind="daily"):
    c = Call(parent_id=p.id, kind=kind, status="completed", scheduled_at=utcnow() - timedelta(days=days_ago))
    session.add(c)
    session.flush()
    a = CallAnalysis(call_id=c.id, mood_score=0.3, text_valence=0.3, prosody=signals)
    session.add(a)
    session.flush()
    return c, a


USUAL = {"source": "audio", "pace_cps": 9.4, "mean_pause_s": 0.55, "loudness_db": -24.0, "pitch_var_st": 2.6}
SLOW = {"source": "audio", "pace_cps": 7.5, "mean_pause_s": 0.9, "loudness_db": -24.5, "pitch_var_st": 2.5}


def test_voice_alert_needs_two_signals_and_history(session):
    p = make_parent(session)
    for d in range(10, 3, -1):
        c, a = _scored(session, p, d, USUAL)
        assert not [x for x in evaluate_after_call(session, p, c, a) if x.kind == "voice"]
    for d in (3, 2):
        c, a = _scored(session, p, d, SLOW)
        evaluate_after_call(session, p, c, a)
    c, a = _scored(session, p, 1, SLOW)
    voice = [x for x in evaluate_after_call(session, p, c, a) if x.kind == "voice"]
    assert len(voice) == 1
    assert "speaking more slowly" in voice[0].reason and "pausing longer" in voice[0].reason
    assert "not a diagnosis" in voice[0].reason


def test_voice_alert_compares_like_with_like(session):
    """Pace from Bolna's speaking time isn't compared with pace measured from audio."""
    p = make_parent(session)
    for d in range(10, 3, -1):
        _scored(session, p, d, USUAL)
    for d in (3, 2, 1):
        c, a = _scored(session, p, d, {"source": "speaking_time", "pace_cps": 6.0})
    assert not [x for x in evaluate_after_call(session, p, c, a) if x.kind == "voice"]


# ---------- medicine reminders ----------

def test_reminder_calls_are_placed_once_and_skip_mood(session, monkeypatch):
    p = make_parent(session)
    session.add(Medicine(parent_id=p.id, name="BP tablet", timing="morning", reminder_time="08:30"))
    session.commit()
    placed = []
    monkeypatch.setattr(settings, "BOLNA_API_KEY", "k")
    monkeypatch.setattr(settings, "BOLNA_AGENT_ID_TE", "agent")
    monkeypatch.setattr(calls.bolna, "place_call", lambda agent, phone, data: placed.append(data) or f"exec-r{len(placed)}")
    monkeypatch.setattr(calls, "_local_now", lambda: utcnow().astimezone(calls.TZ).replace(hour=8, minute=30))
    calls.daily_tick()
    calls.daily_tick()
    assert len(placed) == 1
    assert placed[0]["call_kind"] == "reminder" and placed[0]["reminder_medicine"] == "BP tablet"
    assert "BP tablet" in placed[0]["opening"]
    assert placed[0]["child_message"] == "none"  # messages wait for the evening call

    call = session.exec(select(Call).where(Call.kind == "reminder")).one()
    session.add(CallAnalysis(call_id=call.id, mood_score=-0.9, meds=[{"name": "BP tablet", "status": "taken"}]))
    call.status = "completed"
    session.add(call)
    session.commit()
    assert scored_calls(session, p.id, utcnow() + timedelta(minutes=1)) == []  # not part of her mood
    week = compute_week(session, p)
    assert week["reminders"] == [{"name": "BP tablet", "placed": 1, "answered": 1, "taken": 1}]


def test_missed_reminder_is_not_an_alert(session):
    p = make_parent(session)
    c = Call(parent_id=p.id, kind="reminder", reminder_for="BP tablet", status="missed")
    session.add(c)
    session.commit()
    process.handle_missed(c.id)
    assert session.exec(select(Alert)).all() == []


# ---------- SOS line ----------

def test_caller_lookup_returns_her_context():
    client = TestClient(app)
    from app.db import session_scope

    with session_scope() as s:
        from app.seed import reset

        reset(s)
        p = make_parent(s)
        pid = p.id
    r = client.get("/webhooks/bolna/caller", params={"contact_number": "+919848012345", "execution_id": "in-1", "agent_id": "a"})
    assert r.status_code == 200
    data = r.json()
    assert data["call_kind"] == "inbound" and data["address_term"] == "Amma" and data["opening"]
    with session_scope() as s:
        call = s.exec(select(Call).where(Call.bolna_execution_id == "in-1")).one()
        assert call.kind == "inbound" and call.parent_id == pid
    unknown = client.get("/webhooks/bolna/caller", params={"contact_number": "+911111111111"}).json()
    assert unknown["parent_name"] == "the caller"


def test_inbound_call_alerts_family(session, monkeypatch):
    p = make_parent(session)
    monkeypatch.setattr(process, "download_recording", lambda *a, **k: None)
    monkeypatch.setattr(process, "notify_alert", lambda *a, **k: None)
    monkeypatch.setattr(process, "send_daily_summary", lambda *a, **k: None)
    payload = {"id": "in-2", "status": "completed", "transcript": TRANSCRIPT,
               "telephony_data": {"call_type": "inbound", "from_number": "+919848012345", "to_number": "+918000000000"}}
    outcome = process.handle_execution(payload)
    assert outcome and outcome[0] == "process"
    process.run_outcome(outcome)
    call = session.exec(select(Call).where(Call.bolna_execution_id == "in-2")).one()
    assert call.kind == "inbound" and call.status == "completed"
    alerts = session.exec(select(Alert).where(Alert.call_id == call.id)).all()
    assert [a.kind for a in alerts] == ["sos"]


def test_dropped_inbound_call_rings_her_back(session, monkeypatch):
    p = make_parent(session)
    monkeypatch.setattr(settings, "BOLNA_API_KEY", "k")
    monkeypatch.setattr(settings, "BOLNA_AGENT_ID_TE", "agent")
    monkeypatch.setattr(process, "notify_alert", lambda *a, **k: None)
    placed = []
    monkeypatch.setattr(calls.bolna, "place_call", lambda agent, phone, data: placed.append(data) or "exec-cb")
    payload = {"id": "in-3", "status": "completed", "transcript": "assistant: నమస్తే",
               "telephony_data": {"call_type": "inbound", "from_number": "9848012345"}}
    process.run_outcome(process.handle_execution(payload))
    assert placed and placed[0]["call_kind"] == "callback"
    sos = session.exec(select(Alert).where(Alert.kind == "sos")).one()
    assert "calling her back" in sos.reason
    # She doesn't answer the call back: the family is told to call her.
    cb = session.exec(select(Call).where(Call.kind == "callback")).one()
    cb.status = "missed"
    session.add(cb)
    session.commit()
    process.handle_missed(cb.id)
    assert session.exec(select(Alert).where(Alert.kind == "missed")).one().title.startswith("Amma called Saath")


# ---------- ask her now ----------

def test_ask_now_places_call_with_the_question(session, monkeypatch):
    from app import calls
    from app.config import settings
    from app.db import session_scope

    p = make_parent(session)
    placed = []
    monkeypatch.setattr(settings, "BOLNA_API_KEY", "k")
    monkeypatch.setattr(settings, "BOLNA_AGENT_ID_TE", "agent")
    monkeypatch.setattr(calls.bolna, "place_call", lambda agent, phone, data: placed.append(data) or "exec-ask")
    client = TestClient(app)
    r = client.post(f"/api/parents/{p.id}/ask-now", json={"text": "Did you eat lunch?"})
    assert r.status_code == 200, r.text
    assert r.json()["note"]["is_question"] is True
    assert placed[0]["call_kind"] == "ask" and placed[0]["child_message"] == "Did you eat lunch?"
    assert "Saath" not in placed[0]["opening"] and "today_so_far" in placed[0]
    assert client.post(f"/api/parents/{p.id}/ask-now", json={"text": "  "}).status_code == 400


def test_neighbours_saved_and_rung_on_urgent(session, monkeypatch):
    from app import notify
    from app.config import settings
    from app.models import Family

    p = make_parent(session)
    client = TestClient(app)
    r = client.patch(f"/api/parents/{p.id}", json={"neighbours": [{"name": "Aunty", "phone": "+91 98480 11111"}, {"name": "x", "phone": "12"}]})
    assert r.status_code == 200 and r.json()["neighbours"] == [{"name": "Aunty", "phone": "+919848011111"}]
    placed = []
    monkeypatch.setattr(settings, "BOLNA_API_KEY", "k")
    monkeypatch.setattr(settings, "BOLNA_AGENT_ID_ALERT", "alert")
    monkeypatch.setattr(notify.bolna, "place_call", lambda agent, phone, data: placed.append((phone, data)) or "e")
    a = Alert(parent_id=p.id, kind="urgent", title="t", reason="She said she fell.", talking_points=[])
    session.add(a)
    session.commit()
    fam = session.get(Family, p.family_id)
    fam.child_phone = "+919000000001"
    session.add(fam)
    session.commit()
    notify._deliver(a.id, False)
    phones = [x[0] for x in placed]
    assert "+919000000001" in phones and "+919848011111" in phones
    assert [d["recipient_role"] for ph, d in placed if ph == "+919848011111"] == ["neighbour"]


def test_alert_never_rings_her_own_phone_or_the_child_after_a_transfer(session, monkeypatch):
    from app import notify
    from app.config import settings
    from app.models import Family

    p = make_parent(session)
    fam = session.get(Family, p.family_id)
    fam.child_phone = "+919000000001"
    fam.neighbours = [{"name": "Her own phone", "phone": p.phone}, {"name": "Aunty", "phone": "+919848011111"}, {"name": "Dup", "phone": "+919848011111"}]
    session.add(fam)
    c = Call(parent_id=p.id, kind="daily", status="completed", transferred=True)
    session.add(c)
    session.commit()
    placed = []
    monkeypatch.setattr(settings, "BOLNA_API_KEY", "k")
    monkeypatch.setattr(settings, "BOLNA_AGENT_ID_ALERT", "alert")
    monkeypatch.setattr(notify.bolna, "place_call", lambda agent, phone, data: placed.append(phone) or "e")
    a = Alert(parent_id=p.id, call_id=c.id, kind="urgent", title="t", reason="fell", talking_points=[])
    session.add(a)
    session.commit()
    notify._deliver(a.id, False)
    assert placed == ["+919848011111"]


# ---------- her phone (pairing, SOS, I'm fine) ----------

def test_her_phone_pairing_sos_and_fine(session, monkeypatch):
    from app import her
    from app.models import Family, HerDevice

    p = make_parent(session)
    fam = session.get(Family, p.family_id)
    fam.child_phone = "+919000000001"
    session.add(fam)
    session.commit()
    sent = []
    monkeypatch.setattr(her, "notify_alert", lambda aid, **k: sent.append(aid))
    c = TestClient(app)
    assert c.get("/her").status_code == 200 and c.get("/her/manifest.webmanifest").status_code == 200
    assert c.get("/api/her/me").status_code == 401
    code = c.post(f"/api/parents/{p.id}/pair-code").json()["code"]
    assert c.post("/api/her/pair", json={"code": "000000"}).status_code == 400
    tok = c.post("/api/her/pair", json={"code": code}).json()["token"]
    assert c.post("/api/her/pair", json={"code": code}).status_code == 400  # one use only
    h = {"X-Her-Token": tok}
    me = c.get("/api/her/me", headers=h).json()
    assert me["address_term"] == "Amma" and me["child_phone"] == "+919000000001"
    assert c.post("/api/her/fine", headers=h).status_code == 200
    assert c.post("/api/her/sos", headers=h).json() == {"ok": True}
    assert c.post("/api/her/sos", headers=h).json().get("repeat") is True  # no spam within a minute
    assert len(sent) == 1
    a = session.exec(select(Alert).where(Alert.parent_id == p.id, Alert.kind == "urgent")).all()
    assert len(a) == 1 and "SOS" in a[0].title
    st = c.get(f"/api/parents/{p.id}/her-phone").json()
    assert st["paired"] and st["devices"][0]["last_sos"]
    c.delete(f"/api/parents/{p.id}/her-phone")
    assert c.get("/api/her/me", headers=h).status_code == 401


def test_auto_seed_fills_an_empty_database_once(monkeypatch):
    from app.config import settings
    from app.db import session_scope
    from app.models import Parent
    from app.seed import reset, seed

    with session_scope() as s:
        reset(s)
    monkeypatch.setattr(settings, "AUTO_SEED", True)
    first = seed(False)
    assert seed(False) == first  # second start does nothing
    with session_scope() as s:
        assert len(s.exec(select(Parent)).all()) == 1


# ---------- family password ----------

def test_password_protects_family_api_but_not_her_phone_or_webhooks(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "APP_PASSWORD", "s3cret")
    c = TestClient(app)
    assert c.get("/api/parents").status_code == 401
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/auth/status").json() == {"required": True, "authed": False}
    assert c.get("/api/her/me").status_code == 401  # its own check, not the family one
    assert c.get("/her").status_code == 200
    assert c.get("/webhooks/bolna/caller", params={"contact_number": "+911111111111"}).status_code == 200
    assert c.post("/api/auth/login", json={"password": "nope"}).status_code == 401
    assert c.post("/api/auth/login", json={"password": "s3cret"}).status_code == 200
    assert c.get("/api/parents").status_code == 200
    assert c.get("/api/auth/status").json()["authed"] is True
    c.post("/api/auth/logout")
    assert c.get("/api/parents").status_code == 401


# ---- keeping Bolna's Transfer Call number in step with the app ----

def _fake_agent(number):
    import json as _j
    return {
        "agent_name": "Saath Telugu", "agent_type": "other", "call_summary_enabled": False,
        "agent_welcome_message": "{opening}", "webhook_url": "https://x/webhooks/bolna",
        "agent_prompts": {"task_1": {"system_prompt": "p"}},
        "tasks": [{"task_type": "conversation", "tools_config": {"api_tools": {"tools": [], "tools_params": {
            "transfer_call_x": {"method": "POST", "url": "u", "param": _j.dumps({"call_transfer_number": number, "call_sid": "%(call_sid)s"})}}}}}],
    }


def test_transfer_number_follows_the_app(monkeypatch):
    from app import bolna
    store = {"agent": _fake_agent("+919876543210")}
    sent = []

    def fake_api(method, path, body=None):
        if method == "PUT":
            sent.append(body)
            store["agent"]["tasks"] = body["agent_config"]["tasks"]
            return {"status": "updated"}
        import copy
        return copy.deepcopy(store["agent"])

    monkeypatch.setattr(bolna, "_api", fake_api)
    assert bolna.sync_transfer_number("a1", "9876543210", "+91 99999 11111") == "updated"
    assert "+919999911111" in sent[0]["agent_config"]["tasks"][0]["tools_config"]["api_tools"]["tools_params"]["transfer_call_x"]["param"]
    assert sent[0]["agent_config"]["agent_welcome_message"] == "{opening}"
    assert bolna.sync_transfer_number("a1", "9999911111", "+91 99999 11111") == "already set"
    # a number someone set on purpose (not the old one) is left alone
    assert bolna.sync_transfer_number("a1", "9000000000", "+91 88888 77777").startswith("left alone")
    assert len(sent) == 1


def test_transfer_number_found_when_bolna_returns_an_object(monkeypatch):
    from app import bolna
    a = _fake_agent("+919876543210")
    params = a["tasks"][0]["tools_config"]["api_tools"]["tools_params"]["transfer_call_x"]
    import json as _j
    params["param"] = _j.loads(params["param"])  # real Bolna: an object, not a string
    a["memory_config"] = {"enabled": True}  # settings the update call doesn't take: must not be rewritten
    monkeypatch.setattr(bolna, "_api", lambda m, p, b=None: a)
    r = bolna.sync_transfer_number("a1", "9876543210", "9999911111")
    assert r.startswith("change it in Bolna") and "+919876543210" in r and "+919999911111" in r
    monkeypatch.setattr(bolna, "_api", lambda m, p, b=None: {"tasks": [{"tools_config": {}}]})
    assert "no Transfer Call yet" in bolna.sync_transfer_number("a1", "", "9999911111") or "has no Transfer Call" in bolna.sync_transfer_number("a1", "", "9999911111")


def test_transfer_sync_refuses_when_unsafe(monkeypatch):
    from app import bolna
    a = _fake_agent("+919876543210")
    del a["agent_welcome_message"]
    monkeypatch.setattr(bolna, "_api", lambda m, p, b=None: a)
    assert "safely" in bolna.sync_transfer_number("a1", "9876543210", "9999911111")
    b = _fake_agent("+919876543210")
    del b["webhook_url"]  # a full update would silently drop the webhook that scores her calls
    monkeypatch.setattr(bolna, "_api", lambda m, p, b_=None, _b=b: _b)
    assert "webhook_url" in bolna.sync_transfer_number("a1", "9876543210", "9999911111")
    c = _fake_agent("+919876543210")
    sent = []
    monkeypatch.setattr(bolna, "_api", lambda m, p, body=None: (sent.append(m), c)[1])
    assert bolna.sync_transfer_number("a1", "9876543210", "9999911111", dry_run=True).startswith("would update")
    assert "PUT" not in sent

    def boom(m, p, b=None):
        raise bolna.BolnaError("HTTP 500")
    monkeypatch.setattr(bolna, "_api", boom)
    assert "couldn't" in bolna.sync_transfer_number("a1", "9876543210", "9999911111")
