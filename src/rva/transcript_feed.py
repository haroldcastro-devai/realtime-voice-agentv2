"""Bounded in-process STT/LLM text for the loopback dashboard (no PCM)."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

_MAX_LINES = 64


@dataclass(frozen=True, slots=True)
class TranscriptLine:
    role: str
    text: str


class LiveTranscriptFeed:
    """Thread-safe rolling window of user/agent lines."""

    def __init__(self, max_lines: int = _MAX_LINES) -> None:
        if max_lines < 1:
            raise ValueError("max_lines must be positive")
        self._lock = threading.Lock()
        self._lines: deque[TranscriptLine] = deque(maxlen=max_lines)

    def record_turn(self, user_text: str, agent_text: str) -> None:
        with self._lock:
            if user_text:
                self._lines.append(TranscriptLine(role="user", text=user_text))
            if agent_text:
                self._lines.append(TranscriptLine(role="agent", text=agent_text))

    def snapshot(self) -> list[dict[str, str]]:
        with self._lock:
            copied = list(self._lines)
        return [{"role": row.role, "text": row.text} for row in copied]

    def reset_for_tests(self) -> None:
        with self._lock:
            self._lines.clear()


TRANSCRIPT_FEED = LiveTranscriptFeed()
