"""Sentence TTS prefetch: overlap with play, stable heard order. No network."""

from __future__ import annotations

import threading
import time

import pytest

from rva.prefetch import speak_prefetched, split_sentences

_FRAME = 320


def _pcm(tag: bytes) -> bytes:
    blob = tag[:_FRAME]
    return blob + b"\x00" * (_FRAME - len(blob))


def _assert_frame_contract(chunks: list[bytes]) -> None:
    for blob in chunks:
        assert len(blob) >= _FRAME
        assert len(blob) % _FRAME == 0


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


def test_speak_prefetched_empty_text_does_not_play() -> None:
    tts = _MarkerTts()
    played: list[bytes] = []
    out = speak_prefetched(tts, "", played.append)
    assert out == []
    assert played == []
    assert tts.calls == []
    out = speak_prefetched(tts, "   ", played.append)
    assert out == []
    assert played == []


def test_single_sentence_plays_once_without_extra_synth() -> None:
    tts = _MarkerTts()
    heard: list[bytes] = []
    out = speak_prefetched(tts, "Hello.", heard.append)
    assert tts.calls == ["Hello."]
    assert out == [_pcm(b"Hello.")]
    assert heard == out
    _assert_frame_contract(heard)


def test_heard_order_matches_sentence_order() -> None:
    tts = _MarkerTts()
    played: list[bytes] = []
    text = "Ava at Acme Telco here. You said hello. How can I help?"
    out = speak_prefetched(tts, text, played.append)
    assert tts.calls == [
        "Ava at Acme Telco here.",
        "You said hello.",
        "How can I help?",
    ]
    expected = [
        _pcm(b"Ava at Acme Telco here."),
        _pcm(b"You said hello."),
        _pcm(b"How can I help?"),
    ]
    assert played == expected
    assert out == expected
    _assert_frame_contract(played)


def test_next_synth_overlaps_current_play() -> None:
    """Sentence 2 TTS starts after play(1) begins and before play(1) returns."""
    s1 = "First sentence."
    s2 = "Second sentence."
    play_entered = threading.Event()
    play_release = threading.Event()
    synth2_started = threading.Event()
    played: list[bytes] = []

    class HandshakeTts:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def synthesize(self, text: str) -> bytes:
            self.calls.append(text)
            if text == s2:
                assert play_entered.wait(timeout=1.0), "play must start before prefetch TTS"
                synth2_started.set()
                assert play_release.wait(timeout=1.0), "play must still be in progress"
            return _pcm(text.encode())

    tts = HandshakeTts()

    def play(chunk: bytes) -> None:
        played.append(chunk)
        if chunk == _pcm(s1.encode()):
            play_entered.set()
            assert synth2_started.wait(timeout=1.0), "next TTS must start during play"
            play_release.set()

    heard = speak_prefetched(tts, f"{s1} {s2}", play)
    assert played == [_pcm(s1.encode()), _pcm(s2.encode())]
    assert heard == played
    assert tts.calls == [s1, s2]
    _assert_frame_contract(played)


def test_play_error_consumes_prefetch_future() -> None:
    s1 = "One."
    s2 = "Two."
    tts = _MarkerTts()

    def play(chunk: bytes) -> None:
        if chunk == _pcm(s1.encode()):
            raise RuntimeError("speaker failed")

    with pytest.raises(RuntimeError, match="speaker failed"):
        speak_prefetched(tts, f"{s1} {s2}", play)
    assert tts.calls == [s1, s2]
    assert s2 in tts.ends
