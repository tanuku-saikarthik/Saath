"""Words signal: one LLM call over the native Telugu/Hindi transcript.

This is LLM scoring against a fixed schema, not a trained classifier. If no LLM key is set, a small
keyword heuristic stands in (marked source="mock") so the pipeline still runs during development.
"""
from __future__ import annotations

import logging
from typing import Any

from ..llm import LLMError, chat_json
from .emergency import keyword_emergency

log = logging.getLogger(__name__)

EMOTION_LABELS = [
    "joy", "contentment", "gratitude", "love", "hope", "neutral",
    "sadness", "loneliness", "worry", "fear", "anger", "frustration", "fatigue", "pain", "confusion",
]
MEAL_STATES = ["eaten", "skipped", "unclear", "not_discussed"]
MED_STATES = ["taken", "missed", "unclear", "not_discussed"]

SYSTEM_PROMPT = f"""You analyse the transcript of a short daily check-in phone call between Saath (an AI caller, lines marked "assistant:") and an elderly parent who lives alone (lines marked "user:"). The call is in {{language_name}}.

Score ONLY the parent's lines. Judge how they actually feel, not just what they claim. Older parents often say "all fine" when they are not; note that separately in claimed_fine.

Return ONLY one JSON object, no prose, with exactly these keys:
{{{{
  "emotions": [{{{{"label": one of {EMOTION_LABELS}, "score": 0.0-1.0}}}}],   // multi-label, include every label with score >= 0.2
  "valence": -1.0 to 1.0,          // overall pleasantness of the parent's state
  "arousal": 0.0 to 1.0,           // energy level
  "claimed_fine": true|false,      // did the parent say they are fine / all good at any point
  "evidence": [{{{{"quote_original": "parent's exact words", "quote_en": "English", "signal": "emotion label"}}}}],  // 1-4 items
  "meals": {{{{"breakfast": one of {MEAL_STATES}, "lunch": ..., "dinner": ..., "note": "short English note or empty"}}}},
  "medicines": [{{{{"name": "medicine name as given in the list", "status": one of {MED_STATES}}}}}],
  "worries": ["short English phrases"],
  "health_mentions": ["what she said in plain words, e.g. 'knee pain', 'not sleeping well' (never a diagnosis or medical term)"],
  "emergency": {{{{"flag": true|false, "reason": "short English reason or empty"}}}},   // fall, chest pain, breathlessness, fainting, severe bleeding, confusion about where they are
  "topics": ["short English phrases the parent talked about"],
  "open_threads": ["topics to follow up tomorrow, as short noun phrases like 'Trouble sleeping' or 'Knee pain' (not instructions like 'ask about...')"],
  "avoid_topics": ["topics that clearly upset the parent, short English"],
  "headline": "one English sentence for the child, e.g. 'Amma sounded tired but ate well'",
  "summary": "three short English lines separated by newlines: meals and medicines; mood; what she talked about",
  "transcript_en": "the full conversation rendered in English, keeping the assistant:/user: prefixes",
  "message_delivered": true|false,  // did Saath actually pass on the child's message (given below) during the call
  "reply_to_child": "what the parent asked Saath to tell her child, or her answer to a question the child asked, in English, or empty",
  "consent": "yes" | "no" | "unclear"  // intro calls only: did she agree to daily calls; otherwise "unclear"
}}}}
Use the parent's address term ({{address_term}}) in the headline. Never invent facts that are not in the transcript."""


def _language_name(code: str) -> str:
    return {"te": "Telugu", "hi": "Hindi"}.get(code, "Telugu or Hindi")


def _clamp(x: Any, lo: float, hi: float, default: float = 0.0) -> float:
    try:
        return max(lo, min(hi, float(x)))
    except (TypeError, ValueError):
        return default


def _normalise(raw: dict[str, Any], medicines: list[str]) -> dict[str, Any]:
    emotions = []
    for e in raw.get("emotions") or []:
        label = str(e.get("label", "")).lower().strip()
        if label in EMOTION_LABELS:
            emotions.append({"label": label, "score": round(_clamp(e.get("score"), 0, 1), 3)})
    emotions.sort(key=lambda e: e["score"], reverse=True)

    meals_raw = raw.get("meals") or {}
    meals = {k: (meals_raw.get(k) if meals_raw.get(k) in MEAL_STATES else "not_discussed") for k in ("breakfast", "lunch", "dinner")}
    meals["note"] = str(meals_raw.get("note") or "")

    meds_by_name = {}
    for m in raw.get("medicines") or []:
        name = str(m.get("name", "")).strip()
        status = m.get("status") if m.get("status") in MED_STATES else "unclear"
        if name:
            meds_by_name[name.lower()] = {"name": name, "status": status}
    meds = [meds_by_name.get(n.lower(), {"name": n, "status": "not_discussed"}) for n in medicines]

    emergency = raw.get("emergency") or {}

    def str_list(key: str, limit: int = 6) -> list[str]:
        return [str(x).strip() for x in (raw.get(key) or []) if str(x).strip()][:limit]

    return {
        "emotions": emotions,
        "valence": round(_clamp(raw.get("valence"), -1, 1), 3),
        "arousal": round(_clamp(raw.get("arousal"), 0, 1, 0.5), 3),
        "claimed_fine": bool(raw.get("claimed_fine")),
        "evidence": [
            {
                "quote_original": str(ev.get("quote_original", "")),
                "quote_en": str(ev.get("quote_en", "")),
                "signal": str(ev.get("signal", "")),
            }
            for ev in (raw.get("evidence") or [])[:4]
        ],
        "meals": meals,
        "meds": meds,
        "worries": str_list("worries"),
        "health_mentions": str_list("health_mentions"),
        "emergency": bool(emergency.get("flag")),
        "emergency_reason": str(emergency.get("reason") or ""),
        "topics": str_list("topics"),
        "open_threads": str_list("open_threads", 3),
        "avoid_topics": str_list("avoid_topics", 3),
        "headline": str(raw.get("headline") or ""),
        "summary": str(raw.get("summary") or ""),
        "transcript_en": str(raw.get("transcript_en") or ""),
        "message_delivered": bool(raw.get("message_delivered")),
        "reply_to_child": str(raw.get("reply_to_child") or "").strip(),
        "consent": str(raw.get("consent") or "unclear").lower() if str(raw.get("consent") or "").lower() in ("yes", "no") else "unclear",
    }


def parent_lines(transcript: str) -> list[str]:
    return [ln.split(":", 1)[1].strip() for ln in transcript.splitlines() if ln.lower().startswith("user:")]


def _mock_score(transcript: str, address_term: str, medicines: list[str], child_message: str = "none") -> dict[str, Any]:
    """Keyword stand-in used only when no LLM key is configured."""
    text = " ".join(parent_lines(transcript)).lower()
    neg = ["tired", "alone", "lonely", "pain", "worried", "sad", "not well", "అలసట", "ఒంటరి", "నొప్పి", "थक", "अकेल", "दर्द"]
    pos = ["good", "happy", "fine", "temple", "బాగ", "సంతోష", "अच्छ", "खुश"]
    n = sum(w in text for w in neg)
    p = sum(w in text for w in pos)
    valence = max(-1.0, min(1.0, 0.25 * (p - n)))
    return _normalise(
        {
            "emotions": [{"label": "sadness" if valence < 0 else "contentment", "score": 0.6}],
            "valence": valence,
            "arousal": 0.4,
            "claimed_fine": "fine" in text or "బాగానే" in text or "ठीक" in text,
            "evidence": [],
            "meals": {},
            "medicines": [],
            "headline": f"{address_term} had her check-in call (mock analysis)",
            "summary": "Mock analysis: set LLM_API_KEY for real scoring.",
            "transcript_en": "",
            "message_delivered": child_message != "none",
        },
        medicines,
    )


def score_transcript(
    transcript: str, *, language: str, address_term: str, medicines: list[str],
    call_kind: str = "daily", child_message: str = "none",
) -> tuple[dict[str, Any], str]:
    """Returns (normalised analysis, source)."""
    try:
        system = SYSTEM_PROMPT.format(language_name=_language_name(language), address_term=address_term)
        user = (
            f"Call type: {call_kind}\n"
            f"Parent's medicines: {', '.join(medicines) or 'none listed'}\n"
            f"Message from her child that Saath was asked to pass on: {child_message}\n\n"
            f"Transcript:\n{transcript.strip()}"
        )
        raw = chat_json([{"role": "system", "content": system}, {"role": "user", "content": user}])
        result, source = _normalise(raw, medicines), "llm"
    except LLMError as exc:
        log.warning("Text scoring fell back to mock: %s", exc)
        result, source = _mock_score(transcript, address_term, medicines, child_message), "mock"

    # Safety net: a keyword hit forces the emergency flag even if the LLM missed it.
    hit = keyword_emergency(transcript)
    result["emergency_by"] = [x for x, on in (("llm", result["emergency"] and source == "llm"), ("keyword", bool(hit))) if on]
    if hit and not result["emergency"]:
        result["emergency"] = True
        result["emergency_reason"] = result["emergency_reason"] or f"Possible {hit}"
    return result, source
