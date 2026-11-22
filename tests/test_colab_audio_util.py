"""Unit tests for colab/audio_util.py (no GPU)."""

from __future__ import annotations

import struct

from colab.audio_util import (
    MAX_SPEAKER_ID,
    NEMO_TTS_HZ,
    OPENAI_PCM_HZ,
    resample_pcm16,
    speaker_id_from_voice,
)


def test_speaker_id_from_voice() -> None:
    assert speaker_id_from_voice("0") == 0
    assert speaker_id_from_voice(str(MAX_SPEAKER_ID)) == MAX_SPEAKER_ID
    assert speaker_id_from_voice("999") == 0
    assert speaker_id_from_voice("ava") == 0


def test_resample_pcm16_downsample_neomo_to_openai() -> None:
    samples = [1000, -1000, 500, -500] * 100
    pcm = struct.pack(f"<{len(samples)}h", *samples)
    out = resample_pcm16(pcm, NEMO_TTS_HZ, OPENAI_PCM_HZ)
    assert len(out) % 2 == 0
    assert len(out) != len(pcm)
