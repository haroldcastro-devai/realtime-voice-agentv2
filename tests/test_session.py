"""Barge-in vs listen using synthetic 8 kHz PCM frames — no recordings."""

from __future__ import annotations

import numpy as np

from rva.audiosocket import HANGUP, PCM, Frame
from rva.session import CallSession, FakeInbound
from rva.vad import EnergyVad, VadConfig


def _tone_8k(n_samples: int = 160, amp: int = 8000) -> bytes:
    t = np.arange(n_samples, dtype=np.float64) / 8000.0
    wave = amp * np.sin(2 * np.pi * 1000.0 * t)
    return np.clip(np.rint(wave), -32768, 32767).astype("<i2").tobytes()


def _silence_8k(n_samples: int = 160) -> bytes:
    return b"\x00\x00" * n_samples


def _pcm(payload: bytes) -> Frame:
    return Frame(kind=PCM, payload=payload)


def _session() -> CallSession:
    return CallSession(
        EnergyVad(VadConfig(rms_threshold=100.0, min_speech_frames=1, hangover_frames=0))
    )


def test_speech_during_listen_is_not_barge_in() -> None:
    session = _session()
    counted = session.listen(FakeInbound([_pcm(_tone_8k()), _pcm(_tone_8k())]))
    assert counted == 0
    assert session.barge_ins == 0
    assert session.agent_speaking is False


def test_speech_during_play_counts_barge_in_and_stops() -> None:
    session = _session()
    outbound = _silence_8k(160 * 8)
    inbound = FakeInbound([_pcm(_silence_8k()), _pcm(_tone_8k()), _pcm(_tone_8k())])
    result = session.play(outbound, inbound)
    assert result.completed is False
    assert result.barge_ins == 1
    assert session.barge_ins == 1
    assert result.outbound_frames < 8
    assert session.agent_speaking is False


def test_silence_during_play_does_not_barge_in() -> None:
    session = _session()
    outbound = _silence_8k(160 * 4)
    inbound = FakeInbound([_pcm(_silence_8k()) for _ in range(6)])
    result = session.play(outbound, inbound)
    assert result.completed is True
    assert result.barge_ins == 0
    assert result.outbound_frames == 4


def test_listen_then_play_only_play_counts() -> None:
    session = _session()
    session.listen(FakeInbound([_pcm(_tone_8k())]))
    assert session.barge_ins == 0
    result = session.play(_silence_8k(160 * 4), FakeInbound([_pcm(_tone_8k())]))
    assert result.completed is False
    assert session.barge_ins == 1


def test_hangup_during_play_stops_without_barge_in() -> None:
    session = _session()
    inbound = FakeInbound([Frame(kind=HANGUP, payload=b"")])
    result = session.play(_silence_8k(160 * 4), inbound)
    assert result.completed is False
    assert result.barge_ins == 0
