"""Pure audio helpers for the Colab NeMo worker (pytest-safe, no FastAPI)."""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import resample_poly

NEMO_TTS_HZ = 44_100
OPENAI_PCM_HZ = 24_000
MAX_SPEAKER_ID = 173


def speaker_id_from_voice(voice: str, *, max_speaker: int = MAX_SPEAKER_ID) -> int:
    """Map OpenAI ``voice`` to NeMo multispeaker id (0..max_speaker); default 0."""
    if voice.isdigit():
        sid = int(voice)
        if 0 <= sid <= max_speaker:
            return sid
    return 0


def resample_pcm16(pcm: bytes, src_hz: int, dst_hz: int) -> bytes:
    """Band-limited PCM16 mono resample."""
    if src_hz <= 0 or dst_hz <= 0:
        raise ValueError("sample rates must be positive")
    if src_hz == dst_hz:
        return pcm
    samples = np.frombuffer(pcm, dtype=np.int16)
    if samples.size == 0:
        return pcm
    gcd = math.gcd(src_hz, dst_hz)
    up, down = dst_hz // gcd, src_hz // gcd
    out = resample_poly(samples.astype(np.float64), up, down)
    clipped = np.clip(out, -32768, 32767).astype(np.int16)
    return clipped.tobytes()
