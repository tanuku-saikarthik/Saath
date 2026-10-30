"""Labelled demo history: 13 evenings for one parent, ending in a 3-call dip with "said fine, sounded low".

Every seeded call has is_seeded=True and is marked in the UI. Alerts and next-call context are NOT
hardcoded: they come from the same rules engine (mood.py, context.py) that real calls go through.

Run from saath/backend:  python -m app.seed  [--reset]
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from .config import settings
from .context import build_context
from .db import engine, init_db
from .models import Alert, Call, CallAnalysis, CallContext, Family, Medicine, Note, Parent
from .mood import evaluate_after_call, missed_alert, sos_alert, urgent_alert_now
from .pipeline.fusion import fuse

TZ = ZoneInfo(settings.TIMEZONE)
MEDS = [("BP tablet", "morning", "08:30"), ("Sugar tablet", "after dinner", "")]

EATEN = {"breakfast": "eaten", "lunch": "eaten", "dinner": "eaten", "note": ""}
TAKEN = [{"name": "BP tablet", "status": "taken"}, {"name": "Sugar tablet", "status": "taken"}]

# (days_ago, text_valence, voice_valence, claimed_fine, emotions, transcript, transcript_en, extra)
DAYS = [
    (13, 0.55, 0.30, True, [("contentment", 0.6), ("joy", 0.4)],
     "assistant: నమస్తే అమ్మా, నేను సాథ్. ఈ రోజు ఎలా గడిచింది?\nuser: బాగుంది నాయనా. పొద్దున గుడికి వెళ్ళాను, చాలా ప్రశాంతంగా ఉంది.\nassistant: చాలా బాగుంది అమ్మా. భోజనం చేశారా? మాత్రలు వేసుకున్నారా?\nuser: అన్నం తిన్నాను. బీపీ మాత్ర పొద్దున్నే వేసుకున్నాను, రాత్రి షుగర్ మాత్ర కూడా వేసుకుంటాను.\nassistant: మంచిది అమ్మా. ఏమైనా ఆందోళనగా ఉందా?\nuser: ఏమీ లేదు, అంతా బాగానే ఉంది.",
     "assistant: Namaste Amma, this is Saath. How was your day?\nuser: It was good, dear. I went to the temple in the morning, it was very peaceful.\nassistant: That's lovely, Amma. Did you eat? Did you take your tablets?\nuser: I had my meal. I took the BP tablet in the morning, and I'll take the sugar tablet tonight.\nassistant: Good, Amma. Is anything worrying you?\nuser: Nothing, everything is fine.",
     {"headline": "Amma had a peaceful temple visit and is keeping up with her tablets", "topics": ["Temple visit"],
      "evidence": [("చాలా ప్రశాంతంగా ఉంది", "It was very peaceful", "contentment")]}),
    (12, 0.45, 0.32, False, [("joy", 0.55), ("contentment", 0.5)],
     "assistant: నమస్తే అమ్మా. ఈ రోజు ఎలా ఉంది?\nuser: బాగుంది. తోటలో మల్లెపూలు పూశాయి, చూసి సంతోషమేసింది.\nassistant: ఎంత బాగుందో! భోజనం, మాత్రలు?\nuser: టిఫిన్, భోజనం రెండూ చేశాను. మాత్రలు వేసుకున్నాను.\nassistant: రేపు ఏమి చేయాలనుకుంటున్నారు?\nuser: పక్కింటి సుజాత వస్తానంది, కలిసి కూరగాయలకు వెళ్తాం.",
     "assistant: Namaste Amma. How is today?\nuser: Good. The jasmine in the garden has bloomed, it made me happy.\nassistant: How lovely! Meals and tablets?\nuser: I had breakfast and lunch. I took my tablets.\nassistant: What are you planning for tomorrow?\nuser: Sujatha from next door said she'll come, we'll go for vegetables together.",
     {"headline": "Amma's jasmine bloomed and she has plans with Sujatha tomorrow", "topics": ["Jasmine in the garden", "Neighbour Sujatha"],
      "open_threads": ["Vegetable shopping with Sujatha"], "evidence": [("చూసి సంతోషమేసింది", "It made me happy", "joy")]}),
    (11, 0.60, 0.35, False, [("joy", 0.7), ("love", 0.5)],
     "assistant: నమస్తే అమ్మా, ఈ రోజు ఎలా గడిచింది?\nuser: ఈ రోజు అర్జున్ వీడియో కాల్ చేశాడు. వాడి స్కూల్ డ్రామాలో రాజు వేషం వేశాడట!\nassistant: అద్భుతం అమ్మా! భోజనం చేశారా?\nuser: అన్నీ తిన్నాను, మాత్రలు కూడా వేసుకున్నాను. చాలా సంతోషంగా ఉంది నాయనా.",
     "assistant: Namaste Amma, how did today go?\nuser: Arjun video-called today. He played the king in his school drama!\nassistant: Wonderful, Amma! Did you eat?\nuser: I ate everything and took my tablets too. I'm very happy, dear.",
     {"headline": "Amma was delighted after Arjun's video call", "topics": ["Grandson Arjun's school drama"],
      "evidence": [("చాలా సంతోషంగా ఉంది", "I'm very happy", "joy")]}),
    (10, 0.35, 0.30, False, [("contentment", 0.4), ("pain", 0.4)],
     "assistant: నమస్తే అమ్మా. ఈ రోజు ఎలా ఉంది?\nuser: మోకాలు కొంచెం నొప్పిగా ఉంది, అందుకే ఎక్కువ నడవలేదు.\nassistant: అయ్యో. డాక్టర్ దగ్గరికి వెళ్ళాలా?\nuser: అంత పెద్దది కాదు, నూనె రాసుకున్నాను. రెండు రోజుల్లో తగ్గుతుంది.\nassistant: మాత్రలు, భోజనం?\nuser: అన్నీ చేశాను నాయనా.",
     "assistant: Namaste Amma. How is today?\nuser: My knee hurts a little, so I didn't walk much.\nassistant: Oh no. Should you see a doctor?\nuser: It's not that serious, I applied oil. It'll ease in two days.\nassistant: Tablets and meals?\nuser: All done, dear.",
     {"headline": "Amma's knee is sore but she's eating and taking her tablets", "topics": ["Knee pain"],
      "health_mentions": ["Mild knee pain"], "open_threads": ["Knee pain"],
      "evidence": [("మోకాలు కొంచెం నొప్పిగా ఉంది", "My knee hurts a little", "pain")]}),
    (9, 0.50, 0.30, False, [("contentment", 0.6), ("joy", 0.4)],
     "assistant: నమస్తే అమ్మా. మోకాలు ఎలా ఉంది?\nuser: చాలా నయం. ఈ రోజు పులిహోర చేశాను, సుజాతకి కూడా ఇచ్చాను.\nassistant: కార్తీక్ మీకు ఒక మాట చెప్పమన్నారు అమ్మా: ఈ ఆదివారం ఫోన్ చేస్తానని, మోకాలికి విశ్రాంతి ఇవ్వమని. ఆయనకు ఏమైనా చెప్పమంటారా?\nuser: వాడిని కంగారు పడొద్దని చెప్పు, మోకాలు నయమైంది. సంక్రాంతికి ఇంటికి రమ్మను.\nassistant: తప్పకుండా చెప్తాను అమ్మా. మాత్రలు వేసుకున్నారా?\nuser: వేసుకున్నాను నాయనా.",
     "assistant: Namaste Amma. How is your knee?\nuser: Much better. I made pulihora today and gave some to Sujatha too.\nassistant: Karthik asked me to tell you, Amma: he'll call this Sunday, and to rest your knee. Would you like me to tell him anything?\nuser: Tell him not to worry, my knee is better. Ask him to come home for Sankranti.\nassistant: I'll tell him, Amma. Did you take your tablets?\nuser: I did, dear.",
     {"headline": "Amma's knee is better and she wants you home for Sankranti", "topics": ["Cooked pulihora", "Knee better", "Sankranti visit"],
      "note": ("Tell Amma I'll call her this Sunday, and to rest her knee.", "Don't worry, my knee is better. Come home for Sankranti."),
      "evidence": [("చాలా నయం", "Much better", "contentment")]}),
    (8, None, None, False, [], "", "", {"missed": True}),
    (7, 0.40, 0.32, False, [("contentment", 0.5)],
     "assistant: నమస్తే అమ్మా. ఈ రోజు ఎలా ఉంది?\nuser: నిన్న ఫోన్ ఛార్జింగ్ లో పెట్టి మరిచిపోయాను, అందుకే ఎత్తలేదు. సారీ నాయనా.\nassistant: పర్వాలేదు అమ్మా. ఈ రోజు ఎలా గడిచింది?\nuser: బాగానే ఉంది. సుజాత వచ్చింది, కాసేపు మాట్లాడుకున్నాం. మాత్రలు, భోజనం అయ్యాయి.",
     "assistant: Namaste Amma. How is today?\nuser: Yesterday I left the phone charging and forgot, that's why I didn't pick up. Sorry, dear.\nassistant: No problem, Amma. How did today go?\nuser: Fine. Sujatha came over and we chatted for a while. Tablets and meals done.",
     {"headline": "Amma missed yesterday's call because her phone was charging; today was fine", "topics": ["Visit from Sujatha"],
      "evidence": [("బాగానే ఉంది", "Fine", "contentment")]}),
    (6, 0.45, 0.30, False, [("joy", 0.5), ("hope", 0.4)],
     "assistant: నమస్తే అమ్మా. ఈ రోజు ఏం చేశారు?\nuser: వచ్చే వారం గుడిలో ఉత్సవం ఉంది, పూలమాలలు కడుతున్నాం. చాలా పని ఉంది కానీ బాగుంది.\nassistant: చాలా బాగుంది. భోజనం, మాత్రలు?\nuser: అన్నీ అయ్యాయి.",
     "assistant: Namaste Amma. What did you do today?\nuser: There's a festival at the temple next week, we're making flower garlands. Lots of work but it's nice.\nassistant: That's lovely. Meals and tablets?\nuser: All done.",
     {"headline": "Amma is busy making garlands for the temple festival", "topics": ["Temple festival preparations"],
      "open_threads": ["Temple festival next week"], "evidence": [("చాలా పని ఉంది కానీ బాగుంది", "Lots of work but it's nice", "joy")]}),
    (5, 0.45, 0.20, False, [("contentment", 0.5), ("fatigue", 0.5)],
     "assistant: నమస్తే అమ్మా. ఉత్సవం ఎలా జరిగింది?\nuser: ఉత్సవం బాగా జరిగింది, కానీ చాలా అలసటగా ఉంది. కాళ్ళు నొప్పులు.\nassistant: విశ్రాంతి తీసుకోండి అమ్మా. భోజనం చేశారా?\nuser: తిన్నాను, మాత్రలు కూడా.",
     "assistant: Namaste Amma. How did the festival go?\nuser: The festival went well, but I'm very tired. My legs ache.\nassistant: Please rest, Amma. Did you eat?\nuser: I ate, and took my tablets too.",
     {"headline": "The festival went well; Amma is tired and her legs ache", "topics": ["Temple festival"],
      "health_mentions": ["Leg ache from festival work"], "evidence": [("చాలా అలసటగా ఉంది", "I'm very tired", "fatigue")]}),
    (4, 0.25, -0.35, True, [("neutral", 0.4), ("loneliness", 0.35), ("sadness", 0.3)],
     "assistant: నమస్తే అమ్మా. ఈ రోజు ఎలా గడిచింది?\nuser: బాగానే ఉంది... ఉత్సవం అయిపోయాక ఇల్లు నిశ్శబ్దంగా ఉంది.\nassistant: భోజనం చేశారా?\nuser: కొంచెం తిన్నాను. మాత్రలు వేసుకున్నాను.\nassistant: ఏమైనా ఆందోళనగా ఉందా?\nuser: ఏమీ లేదు, అంతా బాగానే ఉంది.",
     "assistant: Namaste Amma. How did today go?\nuser: It was fine... after the festival the house feels quiet.\nassistant: Did you eat?\nuser: I ate a little. I took my tablets.\nassistant: Is anything worrying you?\nuser: Nothing, everything is fine.",
     {"headline": "Amma said she's fine, but the house feels quiet after the festival", "topics": ["Quiet house after the festival"],
      "meals": {"breakfast": "eaten", "lunch": "eaten", "dinner": "unclear", "note": "Ate only a little"},
      "evidence": [("ఇల్లు నిశ్శబ్దంగా ఉంది", "The house feels quiet", "loneliness")]}),
    (3, 0.20, -0.45, True, [("loneliness", 0.5), ("sadness", 0.4)],
     "assistant: నమస్తే అమ్మా. ఈ రోజు ఎలా ఉంది?\nuser: బాగానే ఉన్నాను. ఈ రోజు వంట చేయాలనిపించలేదు, రాత్రికి ఏమీ తినలేదు.\nassistant: అయ్యో అమ్మా. కొంచెం పాలు, పండు అయినా తీసుకోండి. మాత్రలు?\nuser: వేసుకున్నాను. అర్జున్ కి పరీక్షలు, ఎవరూ ఫోన్ చేయలేదు. పర్వాలేదు, వాళ్ళకి పని ఉంటుంది.",
     "assistant: Namaste Amma. How is today?\nuser: I'm fine. I didn't feel like cooking today, I haven't eaten anything tonight.\nassistant: Oh Amma. Please have at least some milk or fruit. Tablets?\nuser: I took them. Arjun has exams, nobody called. It's okay, they're busy.",
     {"headline": "Amma skipped dinner and nobody called her today", "topics": ["Arjun's exams"],
      "meals": {"breakfast": "eaten", "lunch": "eaten", "dinner": "skipped", "note": "Didn't feel like cooking"},
      "open_threads": ["Skipped dinner"], "evidence": [("ఎవరూ ఫోన్ చేయలేదు", "Nobody called", "loneliness"), ("వంట చేయాలనిపించలేదు", "I didn't feel like cooking", "sadness")]}),
    (2, 0.10, -0.50, True, [("loneliness", 0.55), ("fatigue", 0.5), ("sadness", 0.4)],
     "assistant: నమస్తే అమ్మా. ఈ రోజు ఎలా గడిచింది?\nuser: బాగానే ఉన్నాను, కొంచెం అలసట అంతే. రోజంతా ఇంట్లోనే ఉన్నాను.\nassistant: మాత్రలు వేసుకున్నారా అమ్మా?\nuser: పొద్దున్న బీపీ మాత్ర వేసుకున్నానో లేదో గుర్తు లేదు.\nassistant: భోజనం?\nuser: కొంచెం తిన్నాను.",
     "assistant: Namaste Amma. How did today go?\nuser: I'm fine, just a little tired. I stayed home all day.\nassistant: Did you take your tablets, Amma?\nuser: I don't remember if I took the BP tablet this morning.\nassistant: Meals?\nuser: I ate a little.",
     {"headline": "Amma stayed home all day and isn't sure she took her BP tablet", "topics": ["Stayed home all day"],
      "meds": [{"name": "BP tablet", "status": "unclear"}, {"name": "Sugar tablet", "status": "taken"}],
      "meals": {"breakfast": "unclear", "lunch": "eaten", "dinner": "unclear", "note": "Ate only a little"},
      "open_threads": ["Not sure she took her BP tablet"], "evidence": [("కొంచెం అలసట అంతే", "Just a little tired", "fatigue"), ("రోజంతా ఇంట్లోనే ఉన్నాను", "I stayed home all day", "loneliness")]}),
    (1, 0.00, -0.40, True, [("loneliness", 0.5), ("worry", 0.5), ("fatigue", 0.4)],
     "assistant: నమస్తే అమ్మా. ఎలా ఉన్నారు?\nuser: బాగానే ఉన్నాను నాయనా.\nassistant: ఈ రోజు ఏం చేశారు?\nuser: ఏమీ లేదు. ఈ మధ్య ఎవరూ పెద్దగా మాట్లాడట్లేదు. రాత్రిళ్ళు నిద్ర సరిగా పట్టట్లేదు.\nassistant: అలా అనిపించడం సహజమే అమ్మా. సుజాత గారు వస్తుంటారా?\nuser: సుజాత కూడా ఊరు వెళ్ళింది. మాత్రలు వేసుకున్నాను, భోజనం చేశాను.",
     "assistant: Namaste Amma. How are you?\nuser: I'm fine, dear.\nassistant: What did you do today?\nuser: Nothing. Nobody talks much these days. I'm not sleeping well at night.\nassistant: It's natural to feel that way, Amma. Does Sujatha garu visit?\nuser: Sujatha has gone out of town too. I took my tablets and ate.",
     {"headline": "Amma says she's fine, but she isn't sleeping well and feels no one talks to her", "topics": ["Trouble sleeping", "Sujatha away"],
      "worries": ["Feels nobody talks to her much"], "health_mentions": ["Poor sleep"], "open_threads": ["Trouble sleeping", "Sujatha is out of town"],
      "evidence": [("ఎవరూ పెద్దగా మాట్లాడట్లేదు", "Nobody talks much these days", "loneliness"), ("నిద్ర సరిగా పట్టట్లేదు", "Not sleeping well", "worry")]}),
]


def _prosody(days_ago: int) -> dict:
    """Seeded voice signals: her usual for most of the fortnight, then slower, quieter and flatter over
    the last 3 calls (seed data only; real calls are measured from audio in pipeline/prosody.py)."""
    wobble = ((days_ago * 7) % 5 - 2) / 100  # small, fixed day-to-day variation
    slow = {3: 0.82, 2: 0.78, 1: 0.8}.get(days_ago)
    if slow:
        return {"source": "audio", "speech_s": 70.0, "pace_cps": round(9.4 * slow, 2), "pause_ratio": 0.31,
                "mean_pause_s": round(0.88 + wobble, 2), "loudness_db": round(-28.5 - wobble * 20, 1),
                "pitch_hz": 198.0, "pitch_var_st": round(1.75 + wobble, 2)}
    return {"source": "audio", "speech_s": 80.0, "pace_cps": round(9.4 * (1 + wobble), 2), "pause_ratio": 0.2,
            "mean_pause_s": round(0.55 + wobble, 2), "loudness_db": round(-24.0 + wobble * 20, 1),
            "pitch_hz": 206.0, "pitch_var_st": round(2.6 + wobble * 3, 2)}


# A call she made herself to the Saath number (days_ago, hh, mm)
INBOUND = (6, 15, 40,
    "assistant: నమస్తే అమ్మా, నేను సాథ్ ని. చెప్పండి, ఎలా ఉన్నారు? ఏమైనా సహాయం కావాలా?\nuser: ఏమీ లేదు నాయనా, బాగానే ఉన్నాను. కార్తీక్ కి ఒక మాట చెప్పు: వచ్చే వారం గుడి ఉత్సవానికి అర్జున్ ని తీసుకురమ్మను.\nassistant: తప్పకుండా చెప్తాను అమ్మా. ఇంకేమైనా?\nuser: అంతే. ఉత్సవానికి పూలమాలలు కడుతున్నాను, సాయంత్రం మాట్లాడదాం.",
    "assistant: Namaste Amma, this is Saath. Tell me, how are you? Do you need any help?\nuser: Nothing, dear, I'm fine. Give Karthik a message: ask him to bring Arjun for the temple festival next week.\nassistant: I'll tell him, Amma. Anything else?\nuser: That's all. I'm making garlands for the festival, let's talk in the evening.",
    "Amma called to ask you to bring Arjun for the temple festival next week")

# Morning BP tablet reminder calls: (days_ago, outcome) where outcome is taken | missed
REMINDERS = [(6, "taken"), (5, "taken"), (4, "taken"), (3, "taken"), (2, "missed"), (1, "taken")]
REMINDER_TE = "assistant: నమస్తే అమ్మా, నేను సాథ్ ని. మీ BP tablet వేసుకునే సమయం అయ్యింది.\nuser: సరే నాయనా, ఇప్పుడే వేసుకుంటున్నాను.\nassistant: మంచిది అమ్మా. సాయంత్రం మాట్లాడదాం."
REMINDER_EN = "assistant: Namaste Amma, this is Saath. It's time for your BP tablet.\nuser: Okay dear, I'm taking it now.\nassistant: Good, Amma. Let's talk this evening."


def _seed_extras(session: Session, parent: Parent) -> None:
    """The SOS line and medicine reminders, through the same rules as live calls."""
    days_ago, hh, mm, transcript, transcript_en, headline = INBOUND
    when = _local_evening(days_ago, hh, mm)
    c = Call(parent_id=parent.id, kind="inbound", status="completed", bolna_status="completed", scheduled_at=when,
             duration_s=70, transcript=transcript, is_seeded=True, processed_at=when)
    session.add(c)
    session.flush()
    a = CallAnalysis(
        call_id=c.id, source="seed", text_emotions=[{"label": "joy", "score": 0.5}, {"label": "hope", "score": 0.4}],
        text_valence=0.5, arousal=0.5, claimed_fine=True, voice_probs=_voice_probs(0.3), voice_valence=0.3,
        voice_source="parent_channel", mood_score=fuse(0.5, 0.3, "parent_channel", True)[0], meals={}, meds=[],
        topics=["Temple festival", "Bringing Arjun"], headline=headline, transcript_en=transcript_en,
        summary="She called Saath herself to pass on a message.\nMood: bright.", reply_to_child="Bring Arjun for the temple festival next week.",
        evidence=[{"quote_original": "అర్జున్ ని తీసుకురమ్మను", "quote_en": "Ask him to bring Arjun", "signal": "hope"}],
        prosody=_prosody(days_ago), created_at=when,
    )
    session.add(a)
    session.flush()
    evaluate_after_call(session, parent, c, a)
    sos_alert(session, parent, c, headline=headline)
    session.commit()

    for days_ago, outcome in REMINDERS:
        when = _local_evening(days_ago, 8, 30)
        c = Call(parent_id=parent.id, kind="reminder", reminder_for="BP tablet", scheduled_at=when, is_seeded=True,
                 status="completed" if outcome == "taken" else "missed", bolna_status="completed" if outcome == "taken" else "no-answer",
                 duration_s=35 if outcome == "taken" else 0, transcript=REMINDER_TE if outcome == "taken" else "",
                 processed_at=when if outcome == "taken" else None)
        session.add(c)
        session.flush()
        if outcome == "taken":
            session.add(CallAnalysis(
                call_id=c.id, source="seed", text_emotions=[{"label": "contentment", "score": 0.4}], text_valence=0.3,
                arousal=0.4, mood_score=0.3, meals={}, meds=[{"name": "BP tablet", "status": "taken"}],
                headline="Took her BP tablet after Saath's reminder", summary="BP tablet taken.", transcript_en=REMINDER_EN,
                created_at=when,
            ))
    session.commit()


def _call(session: Session, parent: Parent, kind: str, when: datetime, secs: int, tr_te: str, tr_en: str, **kw) -> Call:
    c = Call(parent_id=parent.id, kind=kind, status="completed", bolna_status="completed", scheduled_at=when,
             duration_s=secs, transcript=tr_te, is_seeded=True, processed_at=when, **kw)
    session.add(c)
    session.flush()
    return c


def _analysis(session: Session, c: Call, when: datetime, days_ago: int, tv: float, vv: float, fine: bool, emotions, headline: str,
              summary: str, tr_en: str, **kw) -> CallAnalysis:
    a = CallAnalysis(
        call_id=c.id, source="seed", text_emotions=[{"label": l, "score": s} for l, s in emotions], text_valence=tv,
        arousal=0.5, claimed_fine=fine, voice_probs=_voice_probs(vv), voice_valence=vv, voice_source="parent_channel",
        mood_score=fuse(tv, vv, "parent_channel", fine)[0], headline=headline, summary=summary, transcript_en=tr_en,
        prosody=_prosody(days_ago), created_at=when, **kw,
    )
    session.add(a)
    session.flush()
    return a


def _seed_story(session: Session, parent: Parent) -> None:
    """The moments around the daily calls, so every part of Saath shows up in the sample history:
    intro call, a small fall with a live transfer, a pocket-dial and the callback, and a question the child asked."""
    # 1) Intro call, two weeks ago: she agreed to the daily calls.
    when = _local_evening(14, 18, 30)
    c = _call(session, parent, "intro", when, 60,
              "assistant: నమస్తే అమ్మా, నేను సాథ్ ని. కార్తీక్ చెప్పారు. ప్రతి సాయంత్రం మీతో కాసేపు మాట్లాడొచ్చా?\nuser: సరే నాయనా, మాట్లాడు.",
              "assistant: Namaste Amma, I'm Saath. Karthik told me about you. May I chat with you for a few minutes every evening?\nuser: Okay, dear, go ahead.")
    _analysis(session, c, when, 14, 0.4, 0.3, False, [("contentment", 0.5)], "Amma agreed to the daily calls",
              "She said yes to a short call every evening.", "", consent="yes")

    # 2) A small fall, day 10: she calls Saath, says she's scared to get up, Saath connects her to the child live.
    when = _local_evening(10, 17, 40)
    tr_en = ("assistant: Namaste Amma, this is Saath. Tell me, do you need help?\nuser: Dear, I slipped near the bathroom. My knee hurts. "
             "I'm scared to get up.\nassistant: Don't be scared, Amma. Stay where you are. I'm connecting you to Karthik right now.")
    tr_te = ("assistant: నమస్తే అమ్మా, నేను సాథ్ ని. చెప్పండి, ఏమైనా సహాయం కావాలా?\nuser: నాయనా, బాత్రూమ్ దగ్గర జారిపడ్డాను. మోకాలు నొప్పిగా ఉంది. లేవడానికి భయంగా ఉంది.\n"
             "assistant: భయపడకండి అమ్మా. అక్కడే ఉండండి. ఇప్పుడే కార్తీక్ తో మాట్లాడిస్తాను.")
    c = _call(session, parent, "inbound", when, 95, tr_te, tr_en, transferred=True)
    reason = "She slipped near the bathroom and her knee hurts. She is scared to get up."
    _analysis(session, c, when, 10, -0.3, -0.25, False, [("fear", 0.5), ("pain", 0.5)],
              "Amma slipped at home and Saath connected her to you", "She called Saath after a slip. Saath put her through to you straight away.\nMood: low.",
              tr_en, emergency=True, emergency_reason=reason, health_mentions=["Slipped, sore knee"],
              evidence=[{"quote_original": "లేవడానికి భయంగా ఉంది", "quote_en": "I'm scared to get up", "signal": "fear"}])
    al = urgent_alert_now(session, parent, c, reason)
    if al:
        al.created_at, al.notified = when, "Saath connected her to you"

    # 3) Pocket-dial, day 7: the call dropped before she spoke, Saath rang back, she had pressed the wrong button.
    when = _local_evening(7, 11, 10)
    c = Call(parent_id=parent.id, kind="inbound", status="missed", bolna_status="no-answer", scheduled_at=when, duration_s=4,
             is_seeded=True, processed_at=when)
    session.add(c)
    session.flush()
    sos_alert(session, parent, c, dropped=True)
    back = when + timedelta(minutes=2)
    tr_en = "assistant: Namaste Amma, this is Saath. You called a moment ago.\nuser: Oh, I pressed the wrong button, dear. I was calling Sujatha.\nassistant: No problem, Amma. Have a lovely day."
    tr_te = "assistant: నమస్తే అమ్మా, నేను సాథ్ ని. ఇందాక మీరు ఫోన్ చేశారు.\nuser: అయ్యో, తప్పు బటన్ నొక్కాను నాయనా. సుజాతకి చేద్దామనుకున్నాను.\nassistant: పర్వాలేదు అమ్మా. మంచి రోజు గడపండి."
    c2 = _call(session, parent, "callback", back, 30, tr_te, tr_en)
    _analysis(session, c2, back, 7, 0.4, 0.3, False, [("contentment", 0.5)], "Amma had pressed the wrong button and was calling Sujatha",
              "Her call dropped before she spoke, so Saath rang her back. All fine.\nMood: steady.", tr_en, topics=["Neighbour Sujatha"])

    # 4) A question the child typed in the app, day 5: Saath rang her to ask it and brought back her answer.
    when = _local_evening(5, 12, 20)
    q, r = "Did you eat lunch, Amma? And how is the knee today?", "I had curd rice. The knee is better, don't worry."
    tr_en = f"assistant: Namaste Amma, this is Saath. Karthik asked: {q}\nuser: {r}\nassistant: I'll tell him. Take care, Amma."
    tr_te = ("assistant: నమస్తే అమ్మా, నేను సాథ్ ని. కార్తీక్ అడిగారు: భోజనం చేశారా అమ్మా? మోకాలు ఎలా ఉంది?\n"
             "user: పెరుగన్నం తిన్నాను. మోకాలు తగ్గింది, ఏం ఫర్వాలేదు.\nassistant: చెప్తాను అమ్మా. జాగ్రత్త.")
    c = _call(session, parent, "ask", when, 40, tr_te, tr_en)
    n = Note(parent_id=parent.id, text=q, created_at=when - timedelta(minutes=6), call_id=c.id, delivered_at=when, reply=r, is_question=True)
    session.add(n)
    session.flush()
    c.note_ids = [n.id]
    session.add(c)
    _analysis(session, c, when, 5, 0.4, 0.3, False, [("contentment", 0.5)], "Amma answered your question: she ate and her knee is better",
              "She answered the question you sent.", tr_en, message_delivered=True, reply_to_child=r, meals={"lunch": "eaten"})
    session.commit()


def _age_alerts(session: Session, parent: Parent) -> None:
    """Alerts older than two days have been dealt with; only the recent ones are still waiting for the child."""
    cutoff = datetime.now(ZoneInfo("UTC")) - timedelta(days=2)
    for al in session.exec(select(Alert).where(Alert.parent_id == parent.id)).all():
        created = al.created_at if al.created_at.tzinfo else al.created_at.replace(tzinfo=ZoneInfo("UTC"))
        if created < cutoff and al.seen_at is None:
            al.seen_at = created + timedelta(hours=2)
            session.add(al)
    session.commit()


def _voice_probs(v: float) -> dict[str, float]:
    """Plausible emotion2vec+ style distribution for a seeded voice valence (seed data only)."""
    if v >= 0.25:
        p = {"happy": 0.42, "neutral": 0.45, "sad": 0.05, "surprised": 0.04, "fearful": 0.01, "angry": 0.01, "disgusted": 0.0, "other": 0.01, "unknown": 0.01}
    elif v >= 0.1:
        p = {"happy": 0.28, "neutral": 0.55, "sad": 0.1, "surprised": 0.03, "fearful": 0.01, "angry": 0.01, "disgusted": 0.0, "other": 0.01, "unknown": 0.01}
    else:
        sad = min(0.6, 0.2 + abs(v))
        p = {"happy": 0.04, "neutral": round(0.9 - sad - 0.12, 2), "sad": round(sad, 2), "surprised": 0.01, "fearful": 0.06, "angry": 0.01, "disgusted": 0.0, "other": 0.02, "unknown": 0.02}
    return p


def _local_evening(days_ago: int, hh: int = 19, mm: int = 5) -> datetime:
    d = datetime.now(TZ) - timedelta(days=days_ago)
    local_dt = d.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return local_dt.astimezone(ZoneInfo("UTC"))


def _summary(meals: dict, meds: list[dict], mood_word: str, topics: list[str]) -> str:
    ate = [k for k in ("breakfast", "lunch", "dinner") if meals.get(k) == "eaten"]
    skipped = [k for k in ("breakfast", "lunch", "dinner") if meals.get(k) == "skipped"]
    meal_line = f"Ate {', '.join(ate) or 'little'}" + (f"; skipped {', '.join(skipped)}" if skipped else "")
    med_line = "; ".join(f"{m['name']} {m['status']}" for m in meds)
    return f"{meal_line}. {med_line}.\nMood: {mood_word}.\nTalked about: {', '.join(topics) or 'her day'}."


def reset(session: Session) -> None:
    for model in (Note, Alert, CallContext, CallAnalysis, Call, Medicine, Parent, Family):
        for row in session.exec(select(model)).all():
            session.delete(row)
    session.commit()


def seed(do_reset: bool = False) -> int:
    init_db()
    with Session(engine) as session:
        if do_reset:
            reset(session)
        existing = session.exec(select(Parent)).first()
        if existing:
            print(f"Already seeded (parent id {existing.id}). Use --reset to rebuild.")
            return existing.id

        family = Family(child_name="Karthik")
        session.add(family)
        session.commit()
        session.refresh(family)
        parent = Parent(
            family_id=family.id, name="Lakshmi", address_term="Amma", phone=settings.TEST_PHONE_NUMBER or "+910000000000",
            language="te", call_time="19:00", topics=["Temple visits", "Her jasmine garden", "Grandson Arjun"], consent_status="granted",
        )
        session.add(parent)
        session.commit()
        session.refresh(parent)
        for name, timing, remind in MEDS:
            session.add(Medicine(parent_id=parent.id, name=name, timing=timing, reminder_time=remind))
        session.commit()
        _seed_extras(session, parent)
        _seed_story(session, parent)

        for days_ago, tv, vv, fine, emotions, transcript, transcript_en, extra in DAYS:
            when = _local_evening(days_ago)
            if extra.get("missed"):
                for attempt, kind, offset in ((1, "daily", 0), (2, "retry", 30)):
                    c = Call(parent_id=parent.id, kind=kind, attempt=attempt, status="missed", bolna_status="no-answer",
                             scheduled_at=when + timedelta(minutes=offset), is_seeded=True)
                    session.add(c)
                    session.commit()
                    session.refresh(c)
                missed_alert(session, parent, c)
                session.commit()
                continue

            mood, mismatch = fuse(tv, vv, "parent_channel", fine)
            mood_word = "bright" if mood >= 0.35 else "steady" if mood >= 0.15 else "low" if mood >= -0.1 else "quite low"
            meals = extra.get("meals", EATEN)
            meds = extra.get("meds", TAKEN)
            topics = extra.get("topics", [])
            c = Call(parent_id=parent.id, kind="daily", status="completed", bolna_status="completed", scheduled_at=when,
                     duration_s=150 + 10 * len(transcript.splitlines()), transcript=transcript, is_seeded=True, processed_at=when)
            session.add(c)
            session.commit()
            session.refresh(c)
            a = CallAnalysis(
                call_id=c.id, source="seed",
                text_emotions=[{"label": l, "score": s} for l, s in emotions],
                text_valence=tv, arousal=0.35 if mood < 0.1 else 0.5, claimed_fine=fine,
                evidence=[{"quote_original": o, "quote_en": e, "signal": s} for o, e, s in extra.get("evidence", [])],
                voice_probs=_voice_probs(vv), voice_valence=vv, voice_source="parent_channel",
                mood_score=mood, mismatch=mismatch, meals=meals, meds=meds,
                worries=extra.get("worries", []), health_mentions=extra.get("health_mentions", []), topics=topics,
                open_threads=extra.get("open_threads", []), avoid_topics=[],
                headline=extra["headline"], summary=_summary(meals, meds, mood_word, topics), transcript_en=transcript_en,
                prosody=_prosody(days_ago), created_at=when,
            )
            if extra.get("note"):
                text, reply = extra["note"]
                a.message_delivered, a.reply_to_child = True, reply
                n = Note(parent_id=parent.id, text=text, created_at=when - timedelta(hours=20), call_id=c.id, delivered_at=when, reply=reply)
                session.add(n)
                session.flush()
                c.note_ids = [n.id]
                session.add(c)
            session.add(a)
            session.flush()
            evaluate_after_call(session, parent, c, a)
            session.commit()

        _age_alerts(session, parent)
        build_context(session, parent)
        session.commit()
        n_alerts = len(session.exec(select(Alert).where(Alert.parent_id == parent.id)).all())
        print(f"Seeded parent {parent.id} ({parent.address_term}) with {len(DAYS)} evenings and {n_alerts} rule-generated alerts.")
        return parent.id


def clear_sample() -> None:
    """Remove every sample call and what was derived from it. Real calls and the parent/medicine setup stay."""
    init_db()
    with Session(engine) as session:
        sample_ids = [c.id for c in session.exec(select(Call).where(Call.is_seeded == True)).all()]  # noqa: E712
        real_ids = {c.id for c in session.exec(select(Call).where(Call.is_seeded == False)).all()}  # noqa: E712
        for model in (CallAnalysis, Note, Alert):
            for row in session.exec(select(model)).all():
                cid = getattr(row, "call_id", None)
                # sample rows: tied to a sample call, or (alerts/notes) not tied to any real call
                if cid in sample_ids or (model is not CallAnalysis and cid not in real_ids):
                    session.delete(row)
        for c in session.exec(select(Call).where(Call.is_seeded == True)).all():  # noqa: E712
            session.delete(c)
        session.commit()
        for parent in session.exec(select(Parent)).all():
            build_context(session, parent)
        session.commit()
        print(f"Removed {len(sample_ids)} sample calls and their alerts/notes. Real calls kept: {len(real_ids)}.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="delete all data first")
    ap.add_argument("--clear-sample", action="store_true", help="remove sample calls/alerts, keep real calls")
    args = ap.parse_args()
    clear_sample() if args.clear_sample else seed(args.reset)
