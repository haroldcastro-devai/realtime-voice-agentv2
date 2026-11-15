"""Sentence TTS prefetch: overlap with play, stable heard order. No network."""

from __future__ import annotations

import threading
import time

from rva.prefetch import speak_prefetched, split_sentences

_FRAME = 320


def _pcm(tag: bytes) -> bytes:
    blob = tag[:_FRAME]
    return blob + b"\x00" * (_FRAME - len(blob))


class _MarkerTts:
    def __init__(
        self, hold: dict[str, threading.Event] | None = None, delay_s: float = 0.0
    ) -> None:
        self.calls: list[str] = []
        self.starts: dict[str, float] = {}
        self.ends: dict[str, float] = {}
        self._lock = threading.Lock()
        self._hold = hold or {}
        self._delay_s = delay_s

    def synthesize(self, text: str) -> bytes:
        with self._lock:
            self.calls.append(text)
        gate = self._hold.get(text)
        if gate is not None:
            gate.wait(timeout=1.0)
        with self._lock:
            self.starts[text] = time.monotonic()
        if self._delay_s:
            time.sleep(self._delay_s)
        with self._lock:
            self.ends[text] = time.monotonic()
        return _pcm(text.encode("ascii", "replace"))


def test_split_sentences_keeps_delimiters_on_the_left() -> None:
    assert split_sentences("") == []
    assert split_sentences("   ") == []
    assert split_sentences("Hello.") == ["Hello."]
    assert split_sentences("Hello. How are you? Fine!") == [
        "Hello.",
        "How are you?",
        "Fine!",
    ]


def test_single_sentence_plays_once_without_extra_synth() -> None:
    tts = _MarkerTts()
    heard: list[bytes] = []
    out = speak_prefetched(tts, "Hello.", heard.append)
    assert tts.calls == ["Hello."]
    assert out == [_pcm(b"Hello.")]
    assert heard == out


def test_heard_order_matches_sentence_order() -> None:
    tts = _MarkerTts()
    text = "Ava at Acme Telco here. You said hello. How can I help?"
    heard = speak_prefetched(tts, text, lambda _pcm: None)
    assert tts.calls == [
        "Ava at Acme Telco here.",
        "You said hello.",
        "How can I help?",
    ]
    assert heard == [
        _pcm(b"Ava at Acme Telco here."),
        _pcm(b"You said hello."),
        _pcm(b"How can I help?"),
    ]


def test_next_synth_overlaps_current_play() -> None:
    """Sentence 2 TTS starts after play(1) begins and before play(1) ends."""
    s1 = "First sentence."
    s2 = "Second sentence."
    play_started = threading.Event()
    play_window = (0.0, 0.0)

    tts = _MarkerTts(
        hold={s2: play_started},
        delay_s=0.02,
    )

    def play(chunk: bytes) -> None:
        nonlocal play_window
        t0 = time.monotonic()
        play_started.set()
        time.sleep(0.05)
        t1 = time.monotonic()
        if chunk == _pcm(s1.encode()):
            play_window = (t0, t1)

    heard = speak_prefetched(tts, f"{s1} {s2}", play)
    assert heard == [_pcm(s1.encode()), _pcm(s2.encode())]
    start2 = tts.starts[s2]
    assert play_window[0] <= start2 <= play_window[1]
    assert tts.calls == [s1, s2]
