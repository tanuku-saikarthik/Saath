"""Fuse words and voice into one mood score and the "said fine, sounded low" flag.

All weights and thresholds are PRD starting values to tune on seeded data, not measured results.
"""
from __future__ import annotations

TEXT_WEIGHT = 0.6
VOICE_WEIGHT = 0.4
MIXED_VOICE_WEIGHT = 0.2  # when the recording holds both voices in one channel
MISMATCH_VOICE_MAX = -0.3


def fuse(text_valence: float, voice_valence: float | None, voice_source: str, claimed_fine: bool) -> tuple[float, bool]:
    if voice_valence is None:
        mood = text_valence
    else:
        vw = MIXED_VOICE_WEIGHT if voice_source == "mixed" else VOICE_WEIGHT
        mood = (1 - vw) * text_valence + vw * voice_valence
    mismatch = bool(claimed_fine and voice_valence is not None and voice_valence <= MISMATCH_VOICE_MAX)
    return round(max(-1.0, min(1.0, mood)), 3), mismatch
