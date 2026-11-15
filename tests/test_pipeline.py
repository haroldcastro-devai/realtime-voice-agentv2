"""Pipeline turn with mocks — no network, no recordings."""

from __future__ import annotations

import socket

import pytest

from rva.pipeline import BackendError, MockLlm, MockStt, MockTts, Pipeline, build_pipeline

_BACKEND_KEYS = ("RVA_STT_BACKEND", "RVA_LLM_BACKEND", "RVA_TTS_BACKEND")


def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _block(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("pipeline turn must not use the network")

    monkeypatch.setattr(socket, "create_connection", _block)
    monkeypatch.setattr(socket.socket, "connect", _block)


def test_full_turn_with_mocks_has_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    _block_network(monkeypatch)
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
    assert len(result.tts_pcm) % 320 == 0
    assert result.tts_pcm == b"\x00" * len(result.tts_pcm)


def test_factory_default_mocks_run_a_turn_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in _BACKEND_KEYS:
        monkeypatch.delenv(key, raising=False)
    _block_network(monkeypatch)
    pcm = b"\x00\x00" * 160
    pipe = build_pipeline()
    assert isinstance(pipe.stt, MockStt)
    assert isinstance(pipe.llm, MockLlm)
    assert isinstance(pipe.tts, MockTts)
    result = pipe.turn(pcm, sample_rate=16_000)
    assert result.user_text == "hello"
    assert "Acme Telco" in result.agent_text
    assert "hello" in result.agent_text
    assert pipe.stt.calls == [(pcm, 16_000)]
    assert pipe.llm.calls == ["hello"]
    assert pipe.tts.calls == [result.agent_text]
    assert len(result.tts_pcm) % 320 == 0
    assert result.tts_pcm == b"\x00" * len(result.tts_pcm)


def test_factory_reads_rva_backend_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RVA_STT_BACKEND", "mock")
    monkeypatch.setenv("RVA_LLM_BACKEND", "MOCK")
    monkeypatch.setenv("RVA_TTS_BACKEND", "mock")
    pipe = build_pipeline()
    assert isinstance(pipe.stt, MockStt)


@pytest.mark.parametrize("env_key", _BACKEND_KEYS)
@pytest.mark.parametrize("name", ["http", "whisper"])
def test_factory_rejects_unknown_and_http_names(
    monkeypatch: pytest.MonkeyPatch, env_key: str, name: str
) -> None:
    for key in _BACKEND_KEYS:
        monkeypatch.setenv(key, "mock")
    monkeypatch.setenv(env_key, name)
    with pytest.raises(BackendError, match="later issue"):
        build_pipeline()
