"""Band-limit checks on synthetic tones — no call recordings."""

from __future__ import annotations

import numpy as np
import pytest

from rva.resample import StreamingResampler, resample_s16le


def _tone(rate: int, freq_hz: float, seconds: float, amp: float = 0.6) -> bytes:
    n = int(rate * seconds)
    t = np.arange(n, dtype=np.float64) / rate
    wave = amp * 32767.0 * np.sin(2 * np.pi * freq_hz * t)
    return np.clip(np.rint(wave), -32768, 32767).astype("<i2").tobytes()


def _energy_near(pcm: bytes, rate: int, center_hz: float, half_width_hz: float) -> float:
    x = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
    spec = np.fft.rfft(x * np.hanning(len(x)))
    freqs = np.fft.rfftfreq(len(x), 1.0 / rate)
    band = (freqs >= center_hz - half_width_hz) & (freqs <= center_hz + half_width_hz)
    return float(np.sum(np.abs(spec[band]) ** 2) + 1e-18)


def _db_ratio(numerator: float, denominator: float) -> float:
    return float(10.0 * np.log10(numerator / denominator))


def _naive_decimate_3(pcm: bytes) -> bytes:
    return np.frombuffer(pcm, dtype="<i2")[::3].tobytes()


def _naive_repeat_2(pcm: bytes) -> bytes:
    return np.repeat(np.frombuffer(pcm, dtype="<i2"), 2).tobytes()


def test_8k_to_16k_length_and_tone() -> None:
    src = _tone(8000, 1000.0, 0.25)
    out = resample_s16le(src, 8000, 16000)
    naive = _naive_repeat_2(src)
    assert abs(len(out) - 2 * len(src)) <= 64
    assert _energy_near(out, 16000, 1000.0, 80.0) > _energy_near(out, 16000, 7000.0, 80.0)
    image_filtered = _energy_near(out, 16000, 7000.0, 150.0)
    image_naive = _energy_near(naive, 16000, 7000.0, 150.0)
    assert _db_ratio(image_naive, image_filtered) >= 25.0


def test_24k_to_8k_kills_suppressed_tone_vs_naive() -> None:
    # 6 kHz sits above 8 kHz Nyquist (4 kHz). Naive 24→8 aliases it near 2 kHz.
    src = _tone(24000, 6000.0, 0.25)
    filtered = resample_s16le(src, 24000, 8000)
    naive = _naive_decimate_3(src)
    filtered_alias = _energy_near(filtered, 8000, 2000.0, 120.0)
    naive_alias = _energy_near(naive, 8000, 2000.0, 120.0)
    assert _db_ratio(naive_alias, filtered_alias) >= 30.0


def test_streaming_20ms_frames_keep_1khz() -> None:
    src = _tone(8000, 1000.0, 0.2)
    frame = 8000 // 50 * 2  # 20 ms of s16le
    stream = StreamingResampler(8000, 16000)
    chunks: list[bytes] = []
    for i in range(0, len(src), frame):
        piece = src[i : i + frame]
        if len(piece) < 4:
            break
        chunks.append(stream.process(piece))
    out = b"".join(chunks)
    assert _energy_near(out, 16000, 1000.0, 80.0) > _energy_near(out, 16000, 7000.0, 80.0)


def test_passthrough_same_rate() -> None:
    pcm = _tone(8000, 440.0, 0.05)
    assert resample_s16le(pcm, 8000, 8000) == pcm
    assert StreamingResampler(8000, 8000).process(pcm) == pcm


def test_empty_input() -> None:
    assert resample_s16le(b"", 8000, 16000) == b""
    assert StreamingResampler(8000, 16000).process(b"") == b""


def test_odd_length_rejected() -> None:
    with pytest.raises(ValueError, match="even"):
        resample_s16le(b"\x00", 8000, 16000)
    with pytest.raises(ValueError, match="even"):
        StreamingResampler(8000, 16000).process(b"\x00")


def test_non_positive_rate_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        resample_s16le(b"\x00\x00", 0, 8000)
    with pytest.raises(ValueError, match="positive"):
        StreamingResampler(0, 8000)
