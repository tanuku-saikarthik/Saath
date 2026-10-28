"""How she spoke: pace, pauses, loudness and pitch movement, from her own audio.

These are the classic acoustic wellness signals: people who are tired, low or unwell tend to speak
more slowly, pause longer, speak more quietly and with flatter pitch. Saath compares each call only
with HER usual, never with a population norm, and never treats a change as a diagnosis: it is a
reason for the family to call.

Works on parent-only audio (a browser test call, or the parent's channel of a Bolna recording).
On a mixed recording Saath's own voice would be measured too, so only the pace from Bolna's
"user speaking" time is used there.

All thresholds are starting values to tune on real calls, not measured results.
"""
from __future__ import annotations

import math
import unicodedata
import wave
from pathlib import Path
from typing import Any

import numpy as np

FRAME_S = 0.03
MIN_PAUSE_S = 0.25  # shorter gaps are part of speech
MAX_PAUSE_S = 3.0   # longer gaps are turn changes or the line being quiet, not hesitation
F0_MIN, F0_MAX = 75.0, 400.0


def spoken_chars(text: str) -> int:
    """Letters she said, not counting vowel signs or other combining marks.

    Words aren't comparable across Telugu, Hindi and English (Telugu joins many words into one), so
    pace is measured in letters per second and only ever compared with her own usual.
    """
    return sum(1 for ch in text if unicodedata.category(ch).startswith("L"))


def _read_mono16(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError("expected 16-bit PCM")
        rate, ch = w.getframerate(), w.getnchannels()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x / 32768.0, rate


def _f0(frame: np.ndarray, rate: int) -> float | None:
    """Autocorrelation pitch of one voiced frame, or None when it isn't clearly periodic."""
    f = frame - frame.mean()
    if not np.any(f):
        return None
    ac = np.correlate(f, f, mode="full")[len(f) - 1 :]
    lo, hi = int(rate / F0_MAX), min(int(rate / F0_MIN), len(ac) - 1)
    if hi <= lo or ac[0] <= 0:
        return None
    lag = lo + int(np.argmax(ac[lo:hi]))
    return rate / lag if ac[lag] / ac[0] > 0.45 else None


def analyse_audio(path: Path, text: str = "") -> dict[str, Any]:
    """Measure one recording of her voice. Returns {} if there's too little speech to judge."""
    x, rate = _read_mono16(path)
    n = int(rate * FRAME_S)
    frames = x[: len(x) // n * n].reshape(-1, n)
    if len(frames) < 10:
        return {}
    rms = np.sqrt((frames**2).mean(axis=1)) + 1e-9
    db = 20 * np.log10(rms)
    # Speech = frames well above the recording's own noise floor
    floor = np.percentile(db, 10)
    voiced = db > max(floor + 12, -50)
    speech_s = float(voiced.sum() * FRAME_S)
    if speech_s < 2.0:
        return {}

    # Pauses: silent runs between speech, within the hesitation range
    pauses, run = [], 0
    started = False
    for v in voiced:
        if v:
            if started and run:
                d = run * FRAME_S
                if MIN_PAUSE_S <= d <= MAX_PAUSE_S:
                    pauses.append(d)
            started, run = True, 0
        else:
            run += 1
    pause_s = float(sum(pauses))

    # Pitch on the louder voiced frames, in semitones so variation is comparable across voices
    loud = np.where(voiced & (db > np.percentile(db[voiced], 40)))[0]
    f0s = [f for f in (_f0(frames[i], rate) for i in loud[:: max(1, len(loud) // 300)]) if f]
    semis = [12 * math.log2(f / 100.0) for f in f0s]

    out: dict[str, Any] = {
        "source": "audio",
        "speech_s": round(speech_s, 1),
        "pause_ratio": round(pause_s / (speech_s + pause_s), 3) if speech_s + pause_s else 0.0,
        "mean_pause_s": round(pause_s / len(pauses), 2) if pauses else 0.0,
        "loudness_db": round(float(np.median(db[voiced])), 1),
    }
    if len(semis) >= 20:
        out["pitch_hz"] = round(float(np.median(f0s)), 1)
        out["pitch_var_st"] = round(float(np.std(semis)), 2)
    chars = spoken_chars(text)
    if chars and speech_s:
        out["pace_cps"] = round(chars / speech_s, 2)
    return out


def from_speaking_time(text: str, user_speaking_ms: int) -> dict[str, Any]:
    """Pace only, from Bolna's total 'user speaking' time, when her audio isn't on its own channel."""
    chars = spoken_chars(text)
    if not chars or user_speaking_ms < 2000:
        return {}
    return {"source": "speaking_time", "speech_s": round(user_speaking_ms / 1000, 1), "pace_cps": round(chars / (user_speaking_ms / 1000), 2)}


# ---------- comparing with her usual ----------

SIGNALS = {
    # key: (label, direction that suggests strain, relative change that counts, absolute floor)
    "pace_cps": ("speaking pace", -1, 0.15, None),
    "mean_pause_s": ("pauses", +1, 0.20, 0.15),
    "loudness_db": ("loudness", -1, None, 4.0),
    "pitch_var_st": ("pitch movement", -1, 0.25, None),
}
MIN_HISTORY = 5


def compare(history: list[dict[str, Any]], recent: list[dict[str, Any]]) -> dict[str, Any]:
    """Recent calls (last 3) against the median of her earlier calls. Returns per-signal changes."""
    changes: dict[str, Any] = {}
    for key, (label, bad_dir, rel, floor) in SIGNALS.items():
        base_vals = [h[key] for h in history if key in h]
        now_vals = [r[key] for r in recent if key in r]
        if len(base_vals) < MIN_HISTORY or len(now_vals) < 2:
            continue
        base = float(np.median(base_vals))
        now = float(np.mean(now_vals))
        diff = now - base
        strained = (diff * bad_dir) > 0
        if key == "loudness_db":
            notable = abs(diff) >= floor
        else:
            notable = base > 0 and abs(diff) / base >= rel and (floor is None or abs(diff) >= floor)
        changes[key] = {
            "label": label, "usual": round(base, 2), "recent": round(now, 2),
            "change_pct": round(100 * diff / base, 1) if key != "loudness_db" and base else None,
            "change_db": round(diff, 1) if key == "loudness_db" else None,
            "strained": bool(strained and notable),
        }
    return changes


def describe(changes: dict[str, Any]) -> list[str]:
    words = {
        "pace_cps": "speaking more slowly", "mean_pause_s": "pausing longer",
        "loudness_db": "speaking more quietly", "pitch_var_st": "speaking in a flatter voice",
    }
    return [words[k] for k, c in changes.items() if c["strained"]]


def measure_call(audio_path: str, parent_text: str, user_speaking_ms: int = 0, parent_only: bool = False) -> dict[str, Any]:
    """Voice signals for one call. Uses her own audio when it can be separated from Saath's voice,
    else the pace from Bolna's speaking time, else nothing."""
    import shutil
    import tempfile

    from .audio import to_parent_wav

    path = Path(audio_path) if audio_path else None
    if path and path.exists():
        tmp = Path(tempfile.mkdtemp(prefix="saath_prosody_"))
        try:
            wav, source = path, "parent_channel" if parent_only else "mixed"
            if shutil.which("ffmpeg"):
                wav = tmp / "parent.wav"
                source = to_parent_wav(path, wav)
                if parent_only:
                    source = "parent_channel"  # browser test calls record only her turns
            elif path.suffix.lower() != ".wav":
                wav = None
            if wav is not None and source == "parent_channel":
                out = analyse_audio(wav, parent_text)
                if out:
                    return out
        except Exception as exc:  # a bad recording shouldn't fail the call
            import logging

            logging.getLogger(__name__).warning("Voice signals failed: %s", exc)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return from_speaking_time(parent_text, user_speaking_ms)


def find_speaking_ms(payload: Any) -> int:
    """Bolna reports how long the caller spoke (interruption_stats.user_speaking_ms); the exact nesting
    isn't documented, so search the payload for the key."""
    if isinstance(payload, dict):
        for k, v in payload.items():
            if k == "user_speaking_ms" and isinstance(v, (int, float)):
                return int(v)
            found = find_speaking_ms(v)
            if found:
                return found
    elif isinstance(payload, list):
        for v in payload:
            found = find_speaking_ms(v)
            if found:
                return found
    return 0
