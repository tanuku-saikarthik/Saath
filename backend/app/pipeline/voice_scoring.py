"""Voice signal: emotion2vec+ large on the parent's speech.

emotion2vec+ is not trained specifically on Telugu or Hindi, so this is presented as a tone signal
beside the words signal, never on its own. Install with: pip install -r requirements-voice.txt
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from ..config import settings
from .audio import to_parent_wav, voiced_chunks

log = logging.getLogger(__name__)

CLASSES = ["angry", "disgusted", "fearful", "happy", "neutral", "other", "sad", "surprised", "unknown"]
# Valence per class (PRD starting values). "other" / "unknown" are dropped and the rest renormalised.
CLASS_VALENCE = {"happy": 1.0, "surprised": 0.3, "neutral": 0.0, "angry": -0.6, "disgusted": -0.6, "fearful": -0.8, "sad": -1.0}

_model = None
_model_error = ""


def _load_model():
    global _model, _model_error
    if _model is not None or _model_error:
        return _model
    try:
        from funasr import AutoModel  # type: ignore

        _model = AutoModel(model=settings.VOICE_MODEL, hub=settings.VOICE_HUB, disable_update=True)
    except Exception as exc:  # funasr/torch missing or download failed
        _model_error = str(exc)
        log.warning("Voice model unavailable, continuing with words only: %s", exc)
    return _model


def model_status() -> dict[str, Any]:
    _load_model()
    return {"loaded": _model is not None, "model": settings.VOICE_MODEL, "hub": settings.VOICE_HUB, "error": _model_error}


def model_dir() -> Path | None:
    path = getattr(_model, "model_path", None) if _model is not None else None
    return Path(path) if path else None


def _label_key(raw: str) -> str:
    # emotion2vec+ labels look like "生气/angry" or "<unk>"
    key = raw.split("/")[-1].strip().lower()
    return "unknown" if "unk" in key else key


def _classify(path: Path) -> dict[str, float]:
    res = _model.generate(str(path), granularity="utterance", extract_embedding=False)
    item = res[0] if isinstance(res, list) else res
    probs = {c: 0.0 for c in CLASSES}
    for label, score in zip(item.get("labels", []), item.get("scores", [])):
        k = _label_key(str(label))
        if k in probs:
            probs[k] += float(score)
    return probs


def valence_from_probs(probs: dict[str, float]) -> float | None:
    known = {k: v for k, v in probs.items() if k in CLASS_VALENCE}
    total = sum(known.values())
    if total <= 1e-6:
        return None
    return round(sum(CLASS_VALENCE[k] * v for k, v in known.items()) / total, 3)


def score_recording(recording: Path) -> dict[str, Any]:
    """Returns {probs, valence, source, segments}. valence is None when the model can't run."""
    empty = {"probs": {}, "valence": None, "source": "none", "segments": []}
    if _load_model() is None:
        return empty
    tmp = Path(tempfile.mkdtemp(prefix="saath_voice_"))
    try:
        wav = tmp / "parent.wav"
        source = to_parent_wav(recording, wav)
        chunks = voiced_chunks(wav, tmp / "chunks")
        if not chunks:
            return {**empty, "source": source}
        total = {c: 0.0 for c in CLASSES}
        weight_sum = 0.0
        segments = []
        for path, start, end in chunks:
            probs = _classify(path)
            w = end - start
            for c in CLASSES:
                total[c] += probs[c] * w
            weight_sum += w
            top = max(probs, key=probs.get)
            segments.append({"start": round(start, 1), "end": round(end, 1), "top": top, "valence": valence_from_probs(probs)})
        avg = {c: round(total[c] / weight_sum, 4) for c in CLASSES}
        return {"probs": avg, "valence": valence_from_probs(avg), "source": source, "segments": segments}
    except Exception as exc:
        log.warning("Voice scoring failed: %s", exc)
        return empty
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
