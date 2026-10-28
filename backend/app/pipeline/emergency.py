"""Keyword safety net for emergencies, checked on the parent's lines only.

The LLM is the primary detector; this list only guarantees an urgent alert if the model misses an
obvious phrase. A negation right next to the phrase ("no chest pain", "ఛాతీ నొప్పి లేదు",
"छाती में दर्द नहीं") cancels the match. Extend the list with phrases heard in real test calls.
"""
from __future__ import annotations

EMERGENCY_PHRASES = {
    # English / romanised. Specific phrases only: "i fell" would also match "I fell asleep".
    "fell down": "fall", "i fell in": "fall", "i had a fall": "fall", "chest pain": "chest pain",
    "can't breathe": "breathlessness", "cannot breathe": "breathlessness", "fainted": "fainting", "ambulance": "ambulance",
    # Telugu
    "పడిపోయాను": "fall", "కింద పడ్డాను": "fall", "జారి పడ్డాను": "fall", "ఛాతీ నొప్పి": "chest pain",
    "ఊపిరి ఆడటం లేదు": "breathlessness", "కళ్ళు తిరిగి": "dizziness/fainting",
    # Hindi
    "गिर गया": "fall", "गिर गई": "fall", "सीने में दर्द": "chest pain", "छाती में दर्द": "chest pain",
    "सांस नहीं": "breathlessness", "बेहोश": "fainting", "चक्कर": "dizziness",
}

# A phrase that itself contains a negation ("ఊపిరి ఆడటం లేదు", "सांस नहीं") is never cancelled.
NEGATIONS_AFTER = ("లేదు", "లేవు", "नहीं", "नही", " no", " not")
NEGATIONS_BEFORE = ("no ", "not ", "never ", "बिना ")
WINDOW = 14  # characters after the phrase checked for a negation


def _negated(text: str, start: int, end: int, phrase: str) -> bool:
    if any(n.strip() in phrase for n in NEGATIONS_AFTER):
        return False
    after = text[end : end + WINDOW]
    before = text[max(0, start - 8) : start]
    return any(n in after for n in NEGATIONS_AFTER) or any(before.endswith(n) for n in NEGATIONS_BEFORE)


def keyword_emergency(transcript: str) -> str:
    """Return the matched reason, or '' if none."""
    parent_text = " ".join(
        ln.split(":", 1)[1] for ln in transcript.splitlines() if ln.lower().startswith("user:")
    ).lower()
    for phrase, reason in EMERGENCY_PHRASES.items():
        start = parent_text.find(phrase)
        while start != -1:
            if not _negated(parent_text, start, start + len(phrase), phrase):
                return reason
            start = parent_text.find(phrase, start + 1)
    return ""
