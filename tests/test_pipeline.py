"""Pipeline turn with mocks — no network, no recordings."""

from __future__ import annotations

import socket

import pytest

from rva.pipeline import (
    BackendError,
    MockLlm,
    MockStt,
    MockTts,
    Pipeline,
    build_pipeline,
)


def test_full_turn_with_mocks_has_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _block(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("pipeline turn must not use the network")

    monkeypatch.setattr(socket, "create_connection", _block)
    monkeypatch.setattr(socket.socket, "connect", _block)

    pcm = b"\x00\x00" * 160
    stt = MockStt("I need my bill")
    llm = MockLlm()
    tts = MockTts()
    result = Pipeline(stt, llm, tts).turn(pcm, sample_rate=16_000)
    assert result.user_text == "I need my bill"
    assert "Acme Telco" in result.agent_text
    assert "I need my bill" in result.agent_text
    assert stt.calls == [(pcm, 16_000)]
    assert llm.calls == ["I need my bill"]
    assert tts.calls == [result.agent_text]
    assert len(result.tts_pcm) >= 320
    assert len(result.tts_pcm) % 2 == 0
    assert result.tts_pcm == b"\x00" * len(result.tts_pcm)


def test_factory_default_mocks_run_a_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RVA_STT_BACKEND", raising=False)
    monkeypatch.delenv("RVA_LLM_BACKEND", raising=False)
    monkeypatch.delenv("RVA_TTS_BACKEND", raising=False)
    pipe = build_pipeline()
    assert isinstance(pipe.stt, MockStt)
    assert isinstance(pipe.llm, MockLlm)
    assert isinstance(pipe.tts, MockTts)
    result = pipe.turn(b"\x00\x00" * 80)
    assert result.user_text == "hello"
    assert "Acme Telco" in result.agent_text
    assert result.tts_pcm


def test_factory_reads_rva_backend_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RVA_STT_BACKEND", "mock")
    monkeypatch.setenv("RVA_LLM_BACKEND", "MOCK")
    monkeypatch.setenv("RVA_TTS_BACKEND", "mock")
    pipe = build_pipeline()
    assert isinstance(pipe.stt, MockStt)


def test_factory_rejects_unknown_and_http_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RVA_STT_BACKEND", "http")
    monkeypatch.setenv("RVA_LLM_BACKEND", "mock")
    monkeypatch.setenv("RVA_TTS_BACKEND", "mock")
    with pytest.raises(BackendError, match="later issue"):
        build_pipeline()
