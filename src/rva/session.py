"""Call session: concurrent inbound AudioSocket read and barge-in.

Barge-in increments only while the agent is playing TTS. User speech in the
listen phase does not abort playback that is not running.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from rva.audiosocket import PCM, Frame, pack_frame
from rva.resample import resample_s16le
from rva.vad import EnergyVad, VadConfig

_SOCK_HZ = 8000
_VAD_HZ = 16000
_FRAME_S16_8K = 320  # 20 ms at 8 kHz


@dataclass
class PlayResult:
    completed: bool
    barge_ins: int
    outbound_frames: int


class CallSession:
    def __init__(self, vad: EnergyVad | None = None) -> None:
        self.vad = vad or EnergyVad(
            VadConfig(rms_threshold=100.0, min_speech_frames=1, hangover_frames=0)
        )
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
        pcm16 = resample_s16le(frame.payload, _SOCK_HZ, _VAD_HZ)
        with self._lock:
            speaking = self._agent_speaking
        if self.vad.decide(pcm16) and speaking:
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
        """
        inbound_iter: Iterator[Frame] = iter(inbound)
        sent = 0
        self._abort.clear()
        with self._lock:
            self._agent_speaking = True
        try:
            for chunk in _chunks(outbound_pcm8k, frame_bytes):
                self._drain_one(inbound_iter)
                if self._abort.is_set():
                    return PlayResult(
                        completed=False, barge_ins=self.barge_ins, outbound_frames=sent
                    )
                self._emit_pcm(chunk, frame_bytes)
                sent += 1
            self._drain_rest(inbound_iter)
            return PlayResult(completed=True, barge_ins=self.barge_ins, outbound_frames=sent)
        finally:
            with self._lock:
                self._agent_speaking = False

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
    for offset in range(0, max(len(pcm), 1), size):
        yield pcm[offset : offset + size]


@dataclass
class FakeInbound:
    """Synthetic AudioSocket PCM frames for tests (no recordings, no TCP)."""

    frames: list[Frame] = field(default_factory=list)

    def __iter__(self) -> Iterator[Frame]:
        return iter(self.frames)
