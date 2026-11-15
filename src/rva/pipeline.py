"""STT / LLM / TTS protocols, in-process mocks, and an env factory.

A full turn is STT → LLM → TTS. ``mock`` backends stay in-process. ``http``
backends are OpenAI-compatible clients (see ``rva.http_backends``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

_MOCK = "mock"
_HTTP = "http"
_FRAME_S16_8K = 320  # 20 ms at 8 kHz s16le


class SpeechToText(Protocol):
    def transcribe(self, pcm: bytes, sample_rate: int = 16_000) -> str: ...


class LanguageModel(Protocol):
    def complete(self, text: str) -> str: ...


class TextToSpeech(Protocol):
    def synthesize(self, text: str) -> bytes:
        """Return mono 8 kHz s16le PCM; length is a multiple of 320 bytes."""
        ...


class BackendError(ValueError):
    """Unknown or not-yet-implemented backend name."""


@dataclass(frozen=True, slots=True)
class TurnResult:
    """One pipeline turn. ``tts_pcm`` is mono 8 kHz s16le, length % 320 == 0."""

    user_text: str
    agent_text: str
    tts_pcm: bytes


class MockStt:
    """Returns a fixed transcript. Ignores PCM bytes (no model, no network)."""

    def __init__(self, transcript: str = "hello") -> None:
        self.transcript = transcript
        self.calls: list[tuple[bytes, int]] = []

    def transcribe(self, pcm: bytes, sample_rate: int = 16_000) -> str:
        self.calls.append((pcm, sample_rate))
        return self.transcript


class MockLlm:
    """Scripted Ava reply for the fictional Acme Telco demo."""

    def __init__(self, reply: str | None = None) -> None:
        self.reply = reply
        self.calls: list[str] = []

    def complete(self, text: str) -> str:
        self.calls.append(text)
        if self.reply is not None:
            return self.reply
        if not text.strip():
            return "This is Ava at Acme Telco. How can I help?"
        return f"Ava at Acme Telco here. You said: {text}"


class MockTts:
    """Emits 8 kHz s16le silence; duration grows with text length."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def synthesize(self, text: str) -> bytes:
        self.calls.append(text)
        frames = max(1, (len(text) + 19) // 20)
        return b"\x00" * (_FRAME_S16_8K * frames)


class Pipeline:
    def __init__(self, stt: SpeechToText, llm: LanguageModel, tts: TextToSpeech) -> None:
        self.stt = stt
        self.llm = llm
        self.tts = tts

    def turn(self, pcm: bytes, sample_rate: int = 16_000) -> TurnResult:
        user_text = self.stt.transcribe(pcm, sample_rate)
        agent_text = self.llm.complete(user_text)
        tts_pcm = self.tts.synthesize(agent_text)
        return TurnResult(user_text=user_text, agent_text=agent_text, tts_pcm=tts_pcm)


def build_pipeline() -> Pipeline:
    """Wire backends from ``RVA_*_BACKEND`` (default ``mock``)."""
    return Pipeline(
        stt=_make_stt(_backend_name("RVA_STT_BACKEND")),
        llm=_make_llm(_backend_name("RVA_LLM_BACKEND")),
        tts=_make_tts(_backend_name("RVA_TTS_BACKEND")),
    )


def _backend_name(env_key: str) -> str:
    raw = os.environ.get(env_key)
    if raw is None or raw == "" or raw == "CHANGE_ME":
        return _MOCK
    return raw.strip().lower()


def _make_stt(name: str) -> SpeechToText:
    if name == _MOCK:
        return MockStt()
    if name == _HTTP:
        from rva.http_backends import HttpStt

        return HttpStt.from_env()
    raise BackendError(f"{name} STT is not available (use mock or http)")


def _make_llm(name: str) -> LanguageModel:
    if name == _MOCK:
        return MockLlm()
    if name == _HTTP:
        from rva.http_backends import HttpLlm

        return HttpLlm.from_env()
    raise BackendError(f"{name} LLM is not available (use mock or http)")


def _make_tts(name: str) -> TextToSpeech:
    if name == _MOCK:
        return MockTts()
    if name == _HTTP:
        from rva.http_backends import HttpTts

        return HttpTts.from_env()
    raise BackendError(f"{name} TTS is not available (use mock or http)")
