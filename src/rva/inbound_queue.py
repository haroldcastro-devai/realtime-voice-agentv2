"""Thread-safe AudioSocket inbound frames for one TCP call."""

from __future__ import annotations

import queue
import threading
from collections.abc import Iterator

from rva.audiosocket import Frame


class InboundQueue:
    """Producer/consumer queue between the socket reader and call session."""

    def __init__(self) -> None:
        self._q: queue.Queue[Frame | None] = queue.Queue()
        self._closed = threading.Event()

    def push(self, frame: Frame) -> None:
        if not self._closed.is_set():
            self._q.put(frame)

    def close(self) -> None:
        if not self._closed.is_set():
            self._closed.set()
            self._q.put(None)

    def get(self, timeout: float | None = None) -> Frame | None:
        if self._closed.is_set() and self._q.empty():
            return None
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def iter_open(self, stop: threading.Event) -> Iterator[Frame]:
        while not stop.is_set():
            frame = self.get(timeout=0.02)
            if frame is None:
                if self._closed.is_set():
                    return
                continue
            yield frame
