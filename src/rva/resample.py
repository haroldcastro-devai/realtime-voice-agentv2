"""Band-limited PCM16 little-endian resample (mono).

``resample_s16le`` uses ``scipy.signal.resample_poly`` on a **complete
buffer**. Do not chop 20 ms frames through that helper: each call builds a
fresh FIR and will click at the seams.

``StreamingResampler`` keeps overlap-save filter state (``lfilter`` ``zi``)
for those 20 ms frames.
"""

from __future__ import annotations

from math import gcd

import numpy as np
from scipy.signal import firwin, lfilter, lfilter_zi, resample_poly

_S16_MIN = -32768
_S16_MAX = 32767
_FIR_TAPS = 129


def resample_s16le(pcm: bytes, src_hz: int, dst_hz: int) -> bytes:
    """Resample packed little-endian int16 mono PCM from ``src_hz`` to ``dst_hz``.

    One-shot API: pass the whole utterance, not isolated 20 ms frames.
    """
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
    return _to_s16le(scaled)


def _to_s16le(samples: np.ndarray) -> bytes:
    clipped = np.clip(np.rint(samples), _S16_MIN, _S16_MAX).astype("<i2")
    return clipped.tobytes()


class StreamingResampler:
    """Polyphase-style FIR with retained ``zi`` for consecutive PCM frames."""

    def __init__(self, src_hz: int, dst_hz: int, taps: int = _FIR_TAPS) -> None:
        if src_hz <= 0 or dst_hz <= 0:
            raise ValueError("sample rates must be positive")
        if taps < 5 or taps % 2 == 0:
            raise ValueError("taps must be odd and >= 5")
        self.src_hz = src_hz
        self.dst_hz = dst_hz
        factor = gcd(src_hz, dst_hz)
        self._up = dst_hz // factor
        self._down = src_hz // factor
        self._b: np.ndarray | None = None
        self._zi: np.ndarray | None = None
        if src_hz == dst_hz:
            return
        cutoff = min(src_hz, dst_hz) / 2.0
        fs_up = src_hz * self._up
        self._b = firwin(taps, cutoff, fs=fs_up, window="hamming")
        self._zi = lfilter_zi(self._b, [1.0]) * 0.0

    def process(self, pcm: bytes) -> bytes:
        if len(pcm) % 2:
            raise ValueError("s16le PCM length must be even")
        if not pcm:
            return b""
        if self.src_hz == self.dst_hz:
            return pcm
        x = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
        if self._b is None or self._zi is None:
            return pcm
        if self._up != 1:
            up = np.zeros(x.size * self._up, dtype=np.float64)
            up[:: self._up] = x * self._up
            x = up
        y, self._zi = lfilter(self._b, [1.0], x, zi=self._zi)
        if self._down != 1:
            y = y[:: self._down]
        return _to_s16le(y)
