"""Recording prep: download, probe channels, isolate the parent, convert to 16 kHz mono WAV chunks."""
from __future__ import annotations

import json
import logging
import math
import struct
import subprocess
import wave
from pathlib import Path

import httpx

from ..config import settings

log = logging.getLogger(__name__)


def download_recording(url: str, dest_stem: Path) -> Path | None:
    """Bolna's recording URL resolves to a pre-signed link that expires after 24 hours, so fetch now."""
    headers = {"Authorization": f"Bearer {settings.BOLNA_API_KEY}"} if settings.BOLNA_API_KEY else {}
    try:
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            ctype = resp.headers.get("content-type", "")
            if "application/json" in ctype:  # endpoint may return the signed link as JSON
                data = resp.json()
                signed = data.get("url") or data.get("recording_url") or data.get("signed_url")
                if not signed:
                    log.warning("Recording JSON had no URL: %s", str(data)[:300])
                    return None
                resp = client.get(signed)
            resp.raise_for_status()
            ext = ".mp3" if "mpeg" in resp.headers.get("content-type", "") else ".wav"
            path = dest_stem.with_suffix(ext)
            path.write_bytes(resp.content)
            return path
    except httpx.HTTPError as exc:
        log.warning("Recording download failed: %s", exc)
        return None


def channel_count(path: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=channels", "-of", "json", str(path)],
        capture_output=True, text=True, check=False,
    )
    try:
        return int(json.loads(out.stdout)["streams"][0]["channels"])
    except (KeyError, IndexError, ValueError, json.JSONDecodeError):
        return 1


def to_parent_wav(src: Path, dest: Path) -> str:
    """Write 16 kHz mono WAV of the parent's voice. Returns voice_source: parent_channel | mixed."""
    channels = channel_count(src)
    if channels >= 2:
        ch = settings.PARENT_CHANNEL if settings.PARENT_CHANNEL < channels else channels - 1
        af = ["-af", f"pan=mono|c0=c{ch}"]
        source = "parent_channel"
    else:
        af = []
        source = "mixed"  # both voices in one channel; down-weighted in fusion
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), *af, "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", str(dest)],
        check=True,
    )
    return source


def voiced_chunks(wav_path: Path, out_dir: Path, seconds: float = 8.0, min_rms: float = 400.0) -> list[tuple[Path, float, float]]:
    """Split a 16-bit mono WAV into fixed chunks, skipping near-silent ones.

    Returns [(chunk_path, start_s, end_s)]. On a parent-only channel, silence = Saath talking.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[tuple[Path, float, float]] = []
    with wave.open(str(wav_path), "rb") as w:
        rate, width = w.getframerate(), w.getsampwidth()
        if width != 2:
            raise ValueError("expected 16-bit PCM")
        frames_per_chunk = int(rate * seconds)
        idx = 0
        while True:
            frames = w.readframes(frames_per_chunk)
            if not frames:
                break
            n = len(frames) // 2
            if n < rate:  # ignore tails under 1 second
                break
            samples = struct.unpack(f"<{n}h", frames[: n * 2])
            rms = math.sqrt(sum(s * s for s in samples) / n)
            start = idx * seconds
            if rms >= min_rms:
                p = out_dir / f"chunk_{idx:04d}.wav"
                with wave.open(str(p), "wb") as cw:
                    cw.setnchannels(1)
                    cw.setsampwidth(2)
                    cw.setframerate(rate)
                    cw.writeframes(frames)
                chunks.append((p, start, start + n / rate))
            idx += 1
    return chunks
