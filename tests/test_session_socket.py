"""Session barge-in, hangup, and TX pacing on a fake socket — no Asterisk."""

from __future__ import annotations

import pytest
from tests.fakesocket import FakeClock, FakeSocket
from tests.test_session import FakeInbound, _pcm, _session, _silence_8k, _tone_8k

from rva.audiosocket import HANGUP, PCM, Frame, parse_frame
from rva.tx import FRAME_PERIOD_S, FRAME_S16_8K


def test_play_on_paces_outbound_on_fake_socket() -> None:
    session = _session()
    clock = FakeClock()
    sock = FakeSocket(clock)
    result = session.play_on(_silence_8k(160 * 4), FakeInbound([]), sock, clock=clock)
    assert result.completed is True
    assert result.barge_ins == 0
    assert result.outbound_frames == 4
    assert len(sock.writes) == 4
    times = [t for t, _ in sock.writes]
    assert times == pytest.approx([0.0, 0.020, 0.040, 0.060])
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert gaps == pytest.approx([FRAME_PERIOD_S] * 3)
    for _, blob in sock.writes:
        parsed = parse_frame(blob)
        assert parsed.kind == PCM
        assert len(parsed.payload) == FRAME_S16_8K


def test_play_on_barge_in_writes_only_packed_prefix() -> None:
    session = _session()
    clock = FakeClock()
    sock = FakeSocket(clock)
    inbound = FakeInbound([_pcm(_silence_8k()), _pcm(_silence_8k()), _pcm(_tone_8k())])
    result = session.play_on(_silence_8k(160 * 8), inbound, sock, clock=clock)
    assert result.completed is False
    assert result.barge_ins == 1
    assert result.outbound_frames == len(sock.writes) == 2
    assert [blob for _, blob in sock.writes] == result.packed
    times = [t for t, _ in sock.writes]
    assert times == pytest.approx([0.0, FRAME_PERIOD_S])
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert gaps == pytest.approx([FRAME_PERIOD_S])
    for blob in result.packed:
        parsed = parse_frame(blob)
        assert parsed.kind == PCM
        assert len(parsed.payload) == FRAME_S16_8K


def test_play_on_hangup_writes_nothing() -> None:
    session = _session()
    clock = FakeClock()
    sock = FakeSocket(clock)
    inbound = FakeInbound([Frame(kind=HANGUP, payload=b"")])
    result = session.play_on(_silence_8k(160 * 4), inbound, sock, clock=clock)
    assert result.completed is False
    assert result.barge_ins == 0
    assert sock.writes == []
    assert clock.sleeps == []


def test_play_on_listen_speech_does_not_barge_or_write_until_play() -> None:
    session = _session()
    session.listen(FakeInbound([_pcm(_tone_8k())]))
    assert session.barge_ins == 0
    clock = FakeClock()
    sock = FakeSocket(clock)
    result = session.play_on(_silence_8k(160 * 4), FakeInbound([]), sock, clock=clock)
    assert result.completed is True
    assert result.barge_ins == 0
    assert len(sock.writes) == 4
