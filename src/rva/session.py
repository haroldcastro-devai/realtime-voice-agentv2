"""Call session: inbound AudioSocket frames and barge-in.

Barge-in increments only while the agent is playing TTS. User speech in the
listen phase, or leftover inbound after TTS ends, does not count as barge-in.

``play()`` interleaves one inbound drain per outbound 20 ms chunk so tests stay
deterministic. Wire paced socket writes through ``play_on`` / ``rva.tx.PacedTx``. A dedicated
inbound reader thread belongs with the TCP server (later issue).
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from rva.audiosocket import PCM, Frame, pack_frame
from rva.resample import StreamingResampler
from rva.tx import Clock, PacedTx, SocketLike
from rva.vad import EnergyVad

_SOCK_HZ = 8000
_VAD_HZ = 16000
_FRAME_S16_8K = 320  # 20 ms at 8 kHz


@dataclass
class PlayResult:
    """Outcome of one ``play()``. ``barge_ins`` is the delta for this call.

    ``packed`` holds AudioSocket PCM frames for ``rva.tx.PacedTx``.
    """

    completed: bool
    barge_ins: int
    outbound_frames: int
    packed: list[bytes] = field(default_factory=list)


class CallSession:
    def __init__(self, vad: EnergyVad | None = None) -> None:
        self.vad = vad or EnergyVad()
        self._inbound_rs = StreamingResampler(_SOCK_HZ, _VAD_HZ)
        self._lock = threading.Lock()
        self._agent_speaking = False
        self._abort = threading.Event()
        self.barge_ins = 0

    @property
    def agent_speaking(self) -> bool:
        with self._lock:
            return self._agent_speaking

    def handle_frame(self, frame: Frame) -> None:
        if frame.is_hangup:
            self._abort.set()
            return
        if not frame.is_pcm or not frame.payload:
            return
        pcm16 = self._inbound_rs.process(frame.payload)
        with self._lock:
            speaking = self._agent_speaking
        if not speaking:
            return
        if self.vad.decide(pcm16):
            with self._lock:
                self.barge_ins += 1
                self._agent_speaking = False
            self._abort.set()

    def play(
        self,
        outbound_pcm8k: bytes,
        inbound: Iterable[Frame],
        frame_bytes: int = _FRAME_S16_8K,
    ) -> PlayResult:
        """Send outbound PCM while draining inbound frames (interleaved).

        Returns ``completed=False`` when barge-in (or hangup) stops playback.
        ``PlayResult.barge_ins`` is the count for this play only; lifetime
        total remains on ``CallSession.barge_ins``.
        """
        inbound_iter: Iterator[Frame] = iter(inbound)
        packed: list[bytes] = []
        before = self.barge_ins
        self._abort.clear()
        self.vad.reset()
        self._inbound_rs.reset()
        with self._lock:
            self._agent_speaking = True
        try:
            for chunk in _chunks(outbound_pcm8k, frame_bytes):
                self._drain_one(inbound_iter)
                if self._abort.is_set():
                    return PlayResult(
                        completed=False,
                        barge_ins=self.barge_ins - before,
                        outbound_frames=len(packed),
                        packed=packed,
                    )
                packed.append(self._emit_pcm(chunk, frame_bytes))
            with self._lock:
                self._agent_speaking = False
            self._drain_rest(inbound_iter)
            return PlayResult(
                completed=True,
                barge_ins=self.barge_ins - before,
                outbound_frames=len(packed),
                packed=packed,
            )
        finally:
            with self._lock:
                self._agent_speaking = False

    def play_on(
        self,
        outbound_pcm8k: bytes,
        inbound: Iterable[Frame],
        sock: SocketLike,
        clock: Clock | None = None,
        frame_bytes: int = _FRAME_S16_8K,
    ) -> PlayResult:
        """``play()`` then pace packed frames onto ``sock`` (injectable clock).

        Does not pass the barge-in abort into ``PacedTx``: frames already packed
        before abort still go on the wire at 20 ms. Hangup with empty ``packed``
        writes nothing. Real TCP belongs to a later issue.
        """
        result = self.play(outbound_pcm8k, inbound, frame_bytes=frame_bytes)
        if result.packed:
            PacedTx(sock, clock=clock).send_frames(result.packed)
        return result

    def listen(self, inbound: Iterable[Frame]) -> int:
        """Process inbound while the agent is silent. Never counts barge-in."""
        before = self.barge_ins
        for frame in inbound:
            self.handle_frame(frame)
        return self.barge_ins - before

    def _drain_one(self, inbound: Iterator[Frame]) -> None:
        try:
            frame = next(inbound)
        except StopIteration:
            return
        self.handle_frame(frame)

    def _drain_rest(self, inbound: Iterator[Frame]) -> None:
        for frame in inbound:
            self.handle_frame(frame)
            if self._abort.is_set():
                return

    def _emit_pcm(self, chunk: bytes, frame_bytes: int) -> bytes:
        if len(chunk) < frame_bytes:
            chunk = chunk + b"\x00" * (frame_bytes - len(chunk))
        return pack_frame(PCM, chunk)


def _chunks(pcm: bytes, size: int) -> Iterable[bytes]:
    if size <= 0:
        raise ValueError("frame size must be positive")
    for offset in range(0, len(pcm), size):
        yield pcm[offset : offset + size]
