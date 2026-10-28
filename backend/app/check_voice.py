"""Check the voice emotion model works on this machine.

    pip install -r requirements-voice.txt
    python -m app.check_voice                 # model's own sample clip, then your latest test call
    python -m app.check_voice path/to/file.wav

The first run downloads the model (from Hugging Face by default; set VOICE_HUB=ms for ModelScope).
It prints the emotion probabilities and the voice valence Saath would use, so you can confirm the
"said fine, sounded low" signal is real before the demo.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from .config import settings
from .pipeline import voice_scoring as vs


def _show(label: str, path: Path) -> bool:
    print(f"\n{label}: {path}")
    if not path.exists():
        print("  (file not found)")
        return False
    t0 = time.time()
    if label.startswith("Model sample"):
        # The bundled sample is one speaker, so classify it directly (no channel split).
        probs = vs._classify(path)
        result = {"probs": probs, "valence": vs.valence_from_probs(probs), "source": "sample", "segments": []}
    else:
        result = vs.score_recording(path)
    took = time.time() - t0
    if result["valence"] is None and not result["probs"]:
        print("  No result: the clip may be silent or too short.")
        return False
    top = sorted(result["probs"].items(), key=lambda kv: -kv[1])[:4]
    print("  top classes: " + ", ".join(f"{k} {v:.2f}" for k, v in top))
    print(f"  voice valence: {result['valence']}  (−1 low … +1 bright)   audio used: {result['source']}   took {took:.1f}s")
    for seg in result["segments"][:6]:
        print(f"    {seg['start']:>5}s–{seg['end']:<5}s  {seg['top']:<10} valence {seg['valence']}")
    return True


def main() -> int:
    print(f"Voice model: {settings.VOICE_MODEL} (hub: {settings.VOICE_HUB})")
    try:
        import funasr  # noqa: F401
    except ImportError:
        print("funasr isn't installed. Run: pip install -r requirements-voice.txt")
        return 1
    print("Loading the model (the first run downloads it, which can take a few minutes)…")
    status = vs.model_status()
    if not status["loaded"]:
        print(f"Couldn't load the model: {status['error']}")
        print("If the download is blocked or slow, try VOICE_HUB=ms (ModelScope) in .env.")
        return 1
    print("Model loaded.")

    ok = False
    if len(sys.argv) > 1:
        ok = _show("Your file", Path(sys.argv[1]))
    else:
        d = vs.model_dir()
        sample = next((p for p in (d / "example" / "test.wav",) if d and p.exists()), None) if d else None
        if sample:
            ok = _show("Model sample clip", sample)
        calls = sorted((settings.DATA_DIR / "testcalls").glob("*/parent.wav"), key=lambda p: p.stat().st_mtime)
        if calls:
            ok = _show("Latest browser test call (parent only)", calls[-1]) or ok
        else:
            print("\nNo browser test calls recorded yet. Do one test call, then run this again to score your own voice.")
    print("\nWorking." if ok else "\nNothing was scored.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
