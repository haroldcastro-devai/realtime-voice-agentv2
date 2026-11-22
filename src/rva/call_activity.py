"""In-process active call counters (ARI Stasis lifecycle)."""

from __future__ import annotations

import threading


class ActiveCallRegistry:
    """Tracks Stasis channels currently in a call."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._channel_ids: set[str] = set()

    def on_stasis_start(self, channel_id: str) -> None:
        with self._lock:
            self._channel_ids.add(channel_id)

    def on_stasis_end(self, channel_id: str) -> None:
        with self._lock:
            self._channel_ids.discard(channel_id)

    def count(self) -> int:
        with self._lock:
            return len(self._channel_ids)

    def reset_for_tests(self) -> None:
        with self._lock:
            self._channel_ids.clear()


REGISTRY = ActiveCallRegistry()
