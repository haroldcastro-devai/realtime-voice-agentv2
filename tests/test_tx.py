"""TX pacing uses a fake clock and fake socket — no wall sleep, no TCP."""

from __future__ import annotations

from threading import Event

import pytest

from rva.audiosocket import PCM, parse_frame
from rva.tx import ABORT_POLL_S, FRAME_PERIOD_S, FRAME_S16_8K, PacedTx


class FakeClock:
    def __init__(self, abort_on_sleep: Event | None = None) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []
        self.abort_on_sleep = abort_on_sleep

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        if self.abort_on_sleep is not None:
            self.abort_on_sleep.set()


class FakeSocket:
    def __init__(
        self,
        clock: FakeClock,
        send_cost: float = 0.0,
        send_costs: list[float] | None = None,
        abort: Event | None = None,
        abort_after: int = 0,
    ) -> None:
        self.clock = clock
        self.send_cost = send_cost
        self.send_costs = send_costs
        self.abort = abort
        self.abort_after = abort_after
        self.writes: list[tuple[float, bytes]] = []

    def sendall(self, data: bytes) -> None:
        self.writes.append((self.clock.now, data))
        cost = self.send_cost
        if self.send_costs is not None:
            cost = self.send_costs.pop(0) if self.send_costs else 0.0
        self.clock.now += cost
        if self.abort is not None and self.abort_after and len(self.writes) >= self.abort_after:
            self.abort.set()


def _silence(n_samples: int) -> bytes:
    return b"\x00\x00" * n_samples


def test_inter_frame_gap_is_20_ms_on_fake_clock() -> None:
    clock = FakeClock()
    sock = FakeSocket(clock)
    pcm = _silence(160 * 5)
    written = PacedTx(sock, clock=clock).send_pcm(pcm)
    assert written == 5
    times = [t for t, _ in sock.writes]
    assert times == pytest.approx([0.0, 0.020, 0.040, 0.060, 0.080])
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert gaps == pytest.approx([FRAME_PERIOD_S] * 4)
    assert clock.sleeps == pytest.approx([FRAME_PERIOD_S] * 5)
    for _, blob in sock.writes:
        frame = parse_frame(blob)
        assert frame.kind == PCM
        assert len(frame.payload) == FRAME_S16_8K


def test_slow_send_shortens_sleep_to_hit_deadline() -> None:
    clock = FakeClock()
    sock = FakeSocket(clock, send_cost=0.015)
    PacedTx(sock, clock=clock).send_pcm(_silence(160 * 3))
    assert [t for t, _ in sock.writes] == pytest.approx([0.0, 0.020, 0.040])
    assert clock.sleeps == pytest.approx([0.005, 0.005, 0.005])


def test_overrun_skips_sleep_and_does_not_go_backward() -> None:
    clock = FakeClock()
    sock = FakeSocket(clock, send_cost=0.025)
    PacedTx(sock, clock=clock).send_pcm(_silence(160 * 3))
    assert [t for t, _ in sock.writes] == pytest.approx([0.0, 0.025, 0.050])
    assert clock.sleeps == []


def test_abort_stops_before_next_write() -> None:
    clock = FakeClock()
    abort = Event()
    sock = FakeSocket(clock, abort=abort, abort_after=2)
    written = PacedTx(sock, clock=clock, abort=abort).send_pcm(_silence(160 * 6))
    assert written == 2
    assert len(sock.writes) == 2
    assert clock.sleeps == pytest.approx([ABORT_POLL_S] * 4)


def test_send_frames_uses_session_packed_blobs() -> None:
    clock = FakeClock()
    sock = FakeSocket(clock)
    from rva.session import CallSession

    session = CallSession()
    result = session.play(_silence(160 * 4), inbound=[])
    written = PacedTx(sock, clock=clock).send_frames(result.packed)
    assert written == result.outbound_frames == 4
    assert [t for t, _ in sock.writes] == pytest.approx([0.0, 0.020, 0.040, 0.060])


def test_single_late_send_does_not_collapse_later_gaps() -> None:
    clock = FakeClock()
    sock = FakeSocket(clock, send_costs=[0.050, 0.0, 0.0, 0.0, 0.0])
    PacedTx(sock, clock=clock).send_pcm(_silence(160 * 5))
    times = [t for t, _ in sock.writes]
    assert times == pytest.approx([0.0, 0.050, 0.070, 0.090, 0.110])
    gaps = [b - a for a, b in zip(times[1:], times[2:])]
    assert gaps == pytest.approx([FRAME_PERIOD_S] * 3)


def test_empty_pcm_writes_nothing() -> None:
    clock = FakeClock()
    sock = FakeSocket(clock)
    written = PacedTx(sock, clock=clock).send_pcm(b"")
    assert written == 0
    assert sock.writes == []
    assert clock.sleeps == []


def test_abort_interrupts_current_slot_wait() -> None:
    abort = Event()
    clock = FakeClock(abort_on_sleep=abort)
    sock = FakeSocket(clock)
    written = PacedTx(sock, clock=clock, abort=abort).send_pcm(_silence(160 * 5))
    assert written == 1
    assert len(sock.writes) == 1
    assert clock.sleeps == pytest.approx([ABORT_POLL_S])


def test_rejects_non_positive_period() -> None:
    clock = FakeClock()
    sock = FakeSocket(clock)
    with pytest.raises(ValueError, match="period_s"):
        PacedTx(sock, clock=clock, period_s=0.0)
