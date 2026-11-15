"""20 ms AudioSocket TX pacing.

Writes packed PCM frames on a socket-like object. Spacing uses an injectable
clock so tests can assert inter-frame timing without wall-clock sleep. A real
TCP connection belongs with the telephony server (later issue).
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from threading import Event
from typing import Protocol

from rva.audiosocket import PCM, pack_frame

FRAME_PERIOD_S = 0.020
FRAME_S16_8K = 320  # 20 ms at 8 kHz s16le
ABORT_POLL_S = 0.005  # interruptible wait while abort is armed


class SocketLike(Protocol):
    def sendall(self, data: bytes, /) -> None: ...


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class WallClock:
    """Production clock: ``time.monotonic`` and ``time.sleep``."""

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


class PacedTx:
    """Send AudioSocket PCM frames one 20 ms slot apart (deadline pacing)."""

    def __init__(
        self,
        sock: SocketLike,
        clock: Clock | None = None,
        abort: Event | None = None,
        period_s: float = FRAME_PERIOD_S,
    ) -> None:
        if period_s <= 0:
            raise ValueError("period_s must be positive")
        self._sock = sock
        self._clock: Clock = clock if clock is not None else WallClock()
        self._abort = abort
        self._period_s = period_s

    def send_pcm(self, pcm: bytes, frame_bytes: int = FRAME_S16_8K) -> int:
        """Chunk 8 kHz s16le PCM, pack, and write on 20 ms deadlines.

        Returns the number of frames written. Stops before a write if ``abort``
        is set. After each write, waits until the next slot unless aborted.
        A late write re-anchors the schedule so later gaps stay one period.
        """
        return self.send_frames(_pack_pcm_chunks(pcm, frame_bytes))

    def send_frames(self, frames: Sequence[bytes] | Iterable[bytes]) -> int:
        """Write already-packed AudioSocket frames on 20 ms deadlines."""
        written = 0
        t0 = self._clock.monotonic()
        for index, blob in enumerate(frames):
            if self._aborted():
                break
            self._sock.sendall(blob)
            written += 1
            if self._aborted():
                break
            now = self._clock.monotonic()
            deadline = t0 + (index + 1) * self._period_s
            remaining = deadline - now
            if remaining <= 0:
                t0 = now - (index + 1) * self._period_s
                continue
            self._wait_until(deadline)
        return written

    def _aborted(self) -> bool:
        return self._abort is not None and self._abort.is_set()

    def _wait_until(self, deadline: float) -> None:
        abort = self._abort
        while True:
            remaining = deadline - self._clock.monotonic()
            if remaining <= 0:
                return
            if abort is not None and abort.is_set():
                return
            if abort is None:
                self._clock.sleep(remaining)
                return
            self._clock.sleep(min(remaining, ABORT_POLL_S))


def _pack_pcm_chunks(pcm: bytes, frame_bytes: int) -> list[bytes]:
    if frame_bytes <= 0:
        raise ValueError("frame_bytes must be positive")
    if len(pcm) % 2:
        raise ValueError("s16le PCM length must be even")
    packed: list[bytes] = []
    for offset in range(0, len(pcm), frame_bytes):
        chunk = pcm[offset : offset + frame_bytes]
        if len(chunk) < frame_bytes:
            chunk = chunk + b"\x00" * (frame_bytes - len(chunk))
        packed.append(pack_frame(PCM, chunk))
    return packed
