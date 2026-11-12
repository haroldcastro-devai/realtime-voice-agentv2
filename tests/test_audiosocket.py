"""Synthetic AudioSocket frames only — no call recordings."""

from __future__ import annotations

import pytest

from rva.audiosocket import (
    ERROR,
    HANGUP,
    PCM,
    UUID,
    FrameError,
    pack_frame,
    parse_frame,
    split_frame,
)


def _pcm(n_samples: int = 160) -> bytes:
    """8 kHz 16-bit LE silence, 20 ms when n_samples=160."""
    return b"\x00\x00" * n_samples


def test_pack_parse_pcm_roundtrip() -> None:
    payload = _pcm()
    raw = pack_frame(PCM, payload)
    frame = parse_frame(raw)
    assert frame.is_pcm
    assert frame.payload == payload
    assert raw[0] == PCM
    assert len(raw) == 3 + len(payload)


def test_uuid_sixteen_bytes_accepted() -> None:
    uid = bytes(range(16))
    frame = parse_frame(pack_frame(UUID, uid))
    assert frame.is_uuid
    assert frame.payload == uid


def test_hangup_empty_payload() -> None:
    frame = parse_frame(pack_frame(HANGUP))
    assert frame.is_hangup
    assert frame.payload == b""


def test_error_kind_roundtrip() -> None:
    frame = parse_frame(pack_frame(ERROR, b"x"))
    assert frame.kind == ERROR
    assert frame.payload == b"x"


def test_truncated_header_rejected() -> None:
    with pytest.raises(FrameError, match="truncated header"):
        parse_frame(b"\x10\x00")


def test_truncated_payload_rejected() -> None:
    header = bytes((PCM, 0x00, 0x04))
    with pytest.raises(FrameError, match="truncated payload"):
        parse_frame(header + b"\x00")


def test_trailing_bytes_rejected() -> None:
    raw = pack_frame(HANGUP) + b"\x00"
    with pytest.raises(FrameError, match="trailing"):
        parse_frame(raw)


def test_uuid_wrong_length_rejected() -> None:
    with pytest.raises(FrameError, match="uuid"):
        pack_frame(UUID, b"\x00" * 15)


def test_unknown_kind_rejected() -> None:
    raw = bytes((0x02, 0x00, 0x00))
    with pytest.raises(FrameError, match="unknown kind"):
        parse_frame(raw)


def test_odd_length_pcm_rejected() -> None:
    with pytest.raises(FrameError, match="pcm"):
        pack_frame(PCM, b"\x00")


def test_split_frame_waits_for_complete_payload() -> None:
    payload = _pcm(2)
    raw = pack_frame(PCM, payload)
    frame, rest = split_frame(raw[:4])
    assert frame is None
    assert rest == raw[:4]
    frame, rest = split_frame(raw)
    assert frame is not None
    assert frame.payload == payload
    assert rest == b""


def test_split_frame_leaves_following_bytes() -> None:
    first = pack_frame(HANGUP)
    second = pack_frame(PCM, _pcm(1))
    frame, rest = split_frame(first + second)
    assert frame is not None
    assert frame.is_hangup
    assert rest == second
