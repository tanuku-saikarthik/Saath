"""Mood rules, fusion and the emergency safety net."""
from datetime import timedelta

from app.models import Alert, Call, CallAnalysis, Family, Parent, utcnow
from app.mood import evaluate_after_call, trend_stats, urgent_alert_now
from app.pipeline.emergency import keyword_emergency
from app.pipeline.fusion import fuse


def make_parent(session):
    fam = Family(child_name="Karthik", child_phone="+919900000001")
    session.add(fam)
    session.commit()
    p = Parent(family_id=fam.id, name="Lakshmi", address_term="Amma", phone="+910000000000", consent_status="granted")
    session.add(p)
    session.commit()
    return p


def add_scored(session, parent, days_ago, mood, emotions=(), mismatch=False):
    c = Call(parent_id=parent.id, status="completed", scheduled_at=utcnow() - timedelta(days=days_ago))
    session.add(c)
    session.commit()
    a = CallAnalysis(call_id=c.id, mood_score=mood, text_valence=mood, mismatch=mismatch,
                     text_emotions=[{"label": l, "score": s} for l, s in emotions])
    session.add(a)
    session.commit()
    return c, a


# ---------- fusion ----------

def test_fusion_weights_and_mismatch():
    assert fuse(0.5, None, "none", True) == (0.5, False)  # no voice: words only, no mismatch possible
    mood, mismatch = fuse(0.2, -0.5, "parent_channel", True)
    assert mood == round(0.6 * 0.2 + 0.4 * -0.5, 3) and mismatch
    assert fuse(0.2, -0.5, "parent_channel", False)[1] is False  # didn't claim fine: no mismatch
    assert fuse(0.2, -0.2, "parent_channel", True)[1] is False  # voice not low enough


def test_mixed_channel_voice_is_down_weighted():
    assert fuse(0.0, -1.0, "mixed", False)[0] == -0.2
    assert fuse(0.0, -1.0, "parent_channel", False)[0] == -0.4


# ---------- trend rules ----------

def test_trend_needs_five_calls():
    assert trend_stats([0.4, 0.4, 0.4, 0.4])["enough"] is False
    assert trend_stats([0.4] * 5)["enough"] is True


def test_one_bad_day_does_not_alert(session):
    p = make_parent(session)
    for d in range(10, 1, -1):
        add_scored(session, p, d, 0.4)
    c, a = add_scored(session, p, 1, -0.6)  # a single very bad evening
    kinds = [x.kind for x in evaluate_after_call(session, p, c, a)]
    assert "drop" not in kinds


def test_sustained_drop_alerts_once_then_cools_down(session):
    p = make_parent(session)
    for d in range(12, 3, -1):
        add_scored(session, p, d, 0.4)
    for d in (3, 2):
        add_scored(session, p, d, -0.1)
    c, a = add_scored(session, p, 1, -0.1)
    first = evaluate_after_call(session, p, c, a)
    session.commit()
    assert [x.kind for x in first] == ["drop"]
    c2, a2 = add_scored(session, p, 0, -0.1)  # next call within 48 h
    assert "drop" not in [x.kind for x in evaluate_after_call(session, p, c2, a2)]


def test_recurring_loneliness(session):
    p = make_parent(session)
    for d in (5, 4, 3, 2):
        add_scored(session, p, d, 0.3, emotions=[("loneliness", 0.6)] if d % 2 == 0 else [("joy", 0.5)])
    c, a = add_scored(session, p, 1, 0.3, emotions=[("loneliness", 0.5)])
    assert "recurring" in [x.kind for x in evaluate_after_call(session, p, c, a)]


def test_urgent_alert_is_created_once_per_call(session):
    p = make_parent(session)
    c, a = add_scored(session, p, 0, -0.2)
    assert urgent_alert_now(session, p, c, "Fell in the bathroom") is not None
    session.commit()
    assert urgent_alert_now(session, p, c, "again") is None  # second mid-call trigger
    a.emergency = True
    assert "urgent" not in [x.kind for x in evaluate_after_call(session, p, c, a)]  # post-call scoring
    session.commit()
    assert session.query(Alert).filter(Alert.kind == "urgent").count() == 1


# ---------- emergency safety net ----------

def test_keywords_catch_emergencies_in_three_languages():
    assert keyword_emergency("user: పొద్దున బాత్రూంలో కింద పడ్డాను") == "fall"
    assert keyword_emergency("user: सीने में दर्द हो रहा है") == "chest pain"
    assert keyword_emergency("user: I fell down the stairs") == "fall"


def test_keywords_ignore_saath_and_harmless_phrases():
    assert keyword_emergency("assistant: did you have chest pain?\nuser: no, all good") == ""
    assert keyword_emergency("user: I fell asleep early last night") == ""


def test_negated_phrases_do_not_trigger():
    assert keyword_emergency("user: ఛాతీ నొప్పి లేదు, కొంచెం అలసట అంతే") == ""
    assert keyword_emergency("user: छाती में दर्द नहीं है, बस थकान है") == ""
    assert keyword_emergency("user: no chest pain, just tired") == ""
    # a phrase that is itself a negation still triggers
    assert keyword_emergency("user: ఊపిరి ఆడటం లేదు") == "breathlessness"
    assert keyword_emergency("user: सांस नहीं आ रही") == "breathlessness"
