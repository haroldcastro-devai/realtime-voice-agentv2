"""Band-limited PCM16 little-endian resample (mono).

Uses ``scipy.signal.resample_poly`` so 8 kHz → 16 kHz and 24 kHz → 8 kHz
apply an anti-alias / interpolation filter. Naive stride copy is not used
on the hot path.
"""

from __future__ import annotations

from math import gcd

import numpy as np
from scipy.signal import resample_poly

_S16_MIN = -32768
_S16_MAX = 32767


def resample_s16le(pcm: bytes, src_hz: int, dst_hz: int) -> bytes:
    """Resample packed little-endian int16 mono PCM from ``src_hz`` to ``dst_hz``."""
    if src_hz <= 0 or dst_hz <= 0:
        raise ValueError("sample rates must be positive")
    if len(pcm) % 2:
        raise ValueError("s16le PCM length must be even")
    if src_hz == dst_hz or not pcm:
        return pcm
    samples = np.frombuffer(pcm, dtype="<i2")
    factor = gcd(src_hz, dst_hz)
    up = dst_hz // factor
    down = src_hz // factor
    floated = samples.astype(np.float64, copy=False)
    scaled = resample_poly(floated, up, down)
    clipped = np.clip(np.rint(scaled), _S16_MIN, _S16_MAX).astype("<i2")
    return clipped.tobytes()
