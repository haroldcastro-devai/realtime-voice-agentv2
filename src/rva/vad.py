"""Energy VAD on 16 kHz little-endian int16 PCM.

Thresholds and hangover/min-speech windows come from ``RVA_VAD_*`` (or a
``VadConfig`` passed in tests). Classification is deterministic for a given
config and PCM bytes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

_DEFAULT_RATE = 16_000


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "" or raw == "CHANGE_ME":
        return default
    return float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "" or raw == "CHANGE_ME":
        return default
    return int(raw)


@dataclass(frozen=True, slots=True)
class VadConfig:
    rms_threshold: float = 500.0
    hangover_frames: int = 4
    min_speech_frames: int = 2
    sample_rate: int = _DEFAULT_RATE

    @classmethod
    def from_env(cls) -> VadConfig:
        return cls(
            rms_threshold=_env_float("RVA_VAD_RMS_THRESHOLD", 500.0),
            hangover_frames=_env_int("RVA_VAD_HANGOVER_FRAMES", 4),
            min_speech_frames=_env_int("RVA_VAD_MIN_SPEECH_FRAMES", 2),
            sample_rate=_env_int("RVA_VAD_SAMPLE_RATE", _DEFAULT_RATE),
        )


def rms_s16le(pcm: bytes) -> float:
    if len(pcm) < 2:
        return 0.0
    samples = np.frombuffer(pcm[: len(pcm) - (len(pcm) % 2)], dtype="<i2")
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))


class EnergyVad:
    """Frame-by-frame speech flag with start hang-in and stop hangover."""

    def __init__(self, config: VadConfig | None = None) -> None:
        self.config = config or VadConfig.from_env()
        if self.config.hangover_frames < 0 or self.config.min_speech_frames < 1:
            raise ValueError("VAD windows must be hangover>=0 and min_speech>=1")
        if self.config.rms_threshold < 0:
            raise ValueError("RVA_VAD_RMS_THRESHOLD must be >= 0")
        self._voiced_run = 0
        self._hang_left = 0
        self._active = False

    def reset(self) -> None:
        self._voiced_run = 0
        self._hang_left = 0
        self._active = False

    def decide(self, pcm: bytes) -> bool:
        loud = rms_s16le(pcm) >= self.config.rms_threshold
        if loud:
            self._voiced_run += 1
            self._hang_left = self.config.hangover_frames
            if self._voiced_run >= self.config.min_speech_frames:
                self._active = True
            return self._active
        self._voiced_run = 0
        if self._active and self._hang_left > 0:
            self._hang_left -= 1
            return True
        self._active = False
        self._hang_left = 0
        return False
