"""End-of-utterance detection on 8 kHz AudioSocket PCM (16 kHz VAD)."""

from __future__ import annotations

from rva.resample import StreamingResampler
from rva.vad import EnergyVad

_SOCK_HZ = 8000
_VAD_HZ = 16000


class UtteranceCollector:
    """Accumulate 16 kHz PCM while VAD is active; flush when speech ends."""

    def __init__(self, vad: EnergyVad | None = None) -> None:
        self._vad = vad or EnergyVad()
        self._rs = StreamingResampler(_SOCK_HZ, _VAD_HZ)
        self._buf = bytearray()
        self._was_active = False

    def reset(self) -> None:
        self._vad.reset()
        self._rs.reset()
        self._buf.clear()
        self._was_active = False

    def feed_pcm8k(self, payload: bytes) -> bytes | None:
        pcm16 = self._rs.process(payload)
        active = self._vad.decide(pcm16)
        if active:
            self._buf.extend(pcm16)
        elif self._was_active and self._buf:
            utterance = bytes(self._buf)
            self.reset()
            return utterance
        self._was_active = active
        return None
