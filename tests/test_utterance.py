"""UtteranceCollector on synthetic PCM."""

from __future__ import annotations

import numpy as np

from rva.utterance import UtteranceCollector
from rva.vad import EnergyVad, VadConfig


def _tone(frames: int = 6) -> bytes:
    payload = b""
    for _ in range(frames):
        t = np.arange(160, dtype=np.float64) / 8000.0
        wave = 9000 * np.sin(2 * np.pi * 1000.0 * t)
        payload += np.clip(np.rint(wave), -32768, 32767).astype("<i2").tobytes()
    return payload


def _silence(frames: int = 8) -> bytes:
    return b"\x00\x00" * (160 * frames)


def test_utterance_flushes_after_speech_hangover() -> None:
    vad = EnergyVad(VadConfig(rms_threshold=100.0, min_speech_frames=2, hangover_frames=2))
    collector = UtteranceCollector(vad)
    frame = _tone(4)
    assert collector.feed_pcm8k(frame[:320]) is None
    assert collector.feed_pcm8k(frame[320:640]) is None
    utterance = None
    for chunk in [_silence(1)] * 6:
        utterance = collector.feed_pcm8k(chunk)
        if utterance:
            break
    assert utterance is not None
    assert len(utterance) >= 320
