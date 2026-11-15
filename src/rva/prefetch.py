"""Sentence-level TTS prefetch: synthesize N+1 while sentence N plays.

Heard order matches ``split_sentences`` order. Does not change ``Pipeline.turn``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

_SPLIT = re.compile(r"(?<=[.!?])\s+")


class SentenceTts(Protocol):
    def synthesize(self, text: str) -> bytes:
        """Return mono 8 kHz s16le PCM; length is a multiple of 320 bytes."""
        ...


def split_sentences(text: str) -> list[str]:
    """Split on ``.`` / ``!`` / ``?`` plus whitespace. Empty input is no sentences."""
    stripped = text.strip()
    if not stripped:
        return []
    return [part.strip() for part in _SPLIT.split(stripped) if part.strip()]


def speak_prefetched(
    tts: SentenceTts,
    text: str,
    play: Callable[[bytes], None],
) -> list[bytes]:
    """Play each sentence in order; prefetch TTS for the next while one plays.

    Returns the PCM chunks passed to ``play``, in heard order.
    """
    sentences = split_sentences(text)
    if not sentences:
        return []

    heard: list[bytes] = []
    with ThreadPoolExecutor(max_workers=1) as pool:
        current = tts.synthesize(sentences[0])
        for index, _sentence in enumerate(sentences):
            nxt = None
            if index + 1 < len(sentences):
                nxt = pool.submit(tts.synthesize, sentences[index + 1])
            play(current)
            heard.append(current)
            if nxt is not None:
                current = nxt.result()
    return heard
