"""Synthetic tones and silence only — no call recordings."""

from __future__ import annotations

import numpy as np
import pytest

from rva.vad import EnergyVad, VadConfig, rms_s16le


def _silence(n_samples: int = 320) -> bytes:
    return b"\x00\x00" * n_samples


def _tone(
    n_samples: int = 320,
    amp: int = 8000,
    freq_hz: float = 1000.0,
    rate: int = 16000,
) -> bytes:
    t = np.arange(n_samples, dtype=np.float64) / rate
    wave = amp * np.sin(2 * np.pi * freq_hz * t)
    return np.clip(np.rint(wave), -32768, 32767).astype("<i2").tobytes()


def test_silence_rms_is_zero() -> None:
    assert rms_s16le(_silence()) == 0.0


def test_silence_is_not_speech() -> None:
    vad = EnergyVad(VadConfig(rms_threshold=100.0, min_speech_frames=1, hangover_frames=0))
    assert not vad.decide(_silence())


def test_tone_is_speech_when_above_threshold() -> None:
    vad = EnergyVad(VadConfig(rms_threshold=100.0, min_speech_frames=1, hangover_frames=0))
    assert vad.decide(_tone())


def test_tone_below_threshold_is_silence() -> None:
    vad = EnergyVad(VadConfig(rms_threshold=20_000.0, min_speech_frames=1, hangover_frames=0))
    assert not vad.decide(_tone(amp=8000))


def test_min_speech_frames_hang_in() -> None:
    vad = EnergyVad(VadConfig(rms_threshold=100.0, min_speech_frames=3, hangover_frames=0))
    assert not vad.decide(_tone())
    assert not vad.decide(_tone())
    assert vad.decide(_tone())


def test_hangover_keeps_speech_through_silence() -> None:
    vad = EnergyVad(VadConfig(rms_threshold=100.0, min_speech_frames=1, hangover_frames=2))
    assert vad.decide(_tone())
    assert vad.decide(_silence())
    assert vad.decide(_silence())
    assert not vad.decide(_silence())


def test_from_env_reads_rva_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RVA_VAD_RMS_THRESHOLD", "1234.5")
    monkeypatch.setenv("RVA_VAD_HANGOVER_FRAMES", "7")
    monkeypatch.setenv("RVA_VAD_MIN_SPEECH_FRAMES", "3")
    monkeypatch.setenv("RVA_VAD_SAMPLE_RATE", "16000")
    cfg = VadConfig.from_env()
    assert cfg.rms_threshold == 1234.5
    assert cfg.hangover_frames == 7
    assert cfg.min_speech_frames == 3
    assert cfg.sample_rate == 16000


def test_silence_resets_hang_in_before_min_speech() -> None:
    vad = EnergyVad(VadConfig(rms_threshold=100.0, min_speech_frames=3, hangover_frames=0))
    assert not vad.decide(_tone())
    assert not vad.decide(_tone())
    assert not vad.decide(_silence())
    assert not vad.decide(_tone())
    assert not vad.decide(_tone())
    assert vad.decide(_tone())


def test_energy_vad_reads_rva_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RVA_VAD_RMS_THRESHOLD", "100")
    monkeypatch.setenv("RVA_VAD_HANGOVER_FRAMES", "0")
    monkeypatch.setenv("RVA_VAD_MIN_SPEECH_FRAMES", "1")
    monkeypatch.setenv("RVA_VAD_SAMPLE_RATE", "16000")
    vad = EnergyVad()
    assert vad.decide(_tone(rate=16000))
    vad.reset()
    assert not vad.decide(_silence())


def test_invalid_windows_rejected() -> None:
    with pytest.raises(ValueError, match="windows"):
        EnergyVad(VadConfig(min_speech_frames=0))


def test_non_16k_sample_rate_rejected() -> None:
    with pytest.raises(ValueError, match="16000"):
        EnergyVad(VadConfig(sample_rate=8000))
