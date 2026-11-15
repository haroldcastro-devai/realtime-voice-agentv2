"""OpenAI-compatible HTTP mapping against a local fake server — no public net."""

from __future__ import annotations

import json
import struct
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import numpy as np
import pytest

from rva.http_backends import HttpLlm, HttpStt, HttpTts
from rva.pipeline import BackendError, build_pipeline
from rva.resample import resample_s16le

_LOOP = "127.0.0.1"


def _tone_24k(n_samples: int, freq_hz: float = 1000.0) -> bytes:
    t = np.arange(n_samples, dtype=np.float64) / 24_000.0
    wave = 0.4 * 32767.0 * np.sin(2 * np.pi * freq_hz * t)
    return np.clip(np.rint(wave), -32768, 32767).astype("<i2").tobytes()


def _make_handler(
    store: list[dict[str, object]],
    *,
    stt_payload: object = "I need my bill",
    llm_text: str = "Ava at Acme Telco here.",
    tts_pcm: bytes | None = None,
    completions: str = "ok",
) -> type[BaseHTTPRequestHandler]:
    if tts_pcm is None:
        tts_pcm = _tone_24k(2400)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _fmt: str, *_args: object) -> None:
            return

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            rec = {
                "path": self.path.split("?", 1)[0],
                "body": self.rfile.read(length),
                "ctype": self.headers.get("Content-Type", ""),
                "auth": self.headers.get("Authorization", ""),
            }
            store.append(rec)
            route = rec["path"]
            if route == "/v1/audio/transcriptions":
                if isinstance(stt_payload, str):
                    self._json(200, {"text": stt_payload})
                else:
                    self._raw(200, json.dumps(stt_payload).encode(), "application/json")
                return
            if route == "/v1/chat/completions":
                if completions == "redirect":
                    self.send_response(302)
                    self.send_header("Location", "/elsewhere")
                    self.end_headers()
                    return
                if completions == "badjson":
                    self._raw(200, b"{not-json", "application/json")
                    return
                if completions == "badutf":
                    self._raw(200, b"\xff\xfe not json", "application/json")
                    return
                self._json(
                    200,
                    {"choices": [{"message": {"role": "assistant", "content": llm_text}}]},
                )
                return
            if route == "/v1/audio/speech":
                self._raw(200, tts_pcm, "application/octet-stream")
                return
            self._json(404, {"error": "unknown-route"})

        def _json(self, code: int, payload: object) -> None:
            self._raw(code, json.dumps(payload).encode(), "application/json")

        def _raw(self, code: int, blob: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            self.wfile.write(blob)

    return Handler


def _start(handler: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((_LOOP, 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _base(server: ThreadingHTTPServer) -> str:
    return f"http://{_LOOP}:{server.server_address[1]}"


def test_http_stt_sends_wav_with_sample_rate() -> None:
    store: list[dict[str, object]] = []
    server = _start(_make_handler(store))
    try:
        client = HttpStt(_base(server), token="rva-test-token", model="rva-stt")
        pcm = b"\x01\x00" * 8
        text = client.transcribe(pcm, sample_rate=16_000)
        assert text == "I need my bill"
        rec = store[-1]
        body = rec["body"]
        assert rec["path"] == "/v1/audio/transcriptions"
        assert rec["auth"] == "Bearer rva-test-token"
        assert "multipart/form-data" in rec["ctype"]
        assert b'filename="audio.wav"' in body
        assert b"audio/wav" in body
        assert b"RIFF" in body
        assert b"WAVE" in body
        assert struct.pack("<I", 16_000) in body
        assert pcm in body
        assert body.strip().endswith(b"--")
    finally:
        server.shutdown()
        server.server_close()


def test_http_llm_maps_chat_completions() -> None:
    store: list[dict[str, object]] = []
    server = _start(_make_handler(store))
    try:
        client = HttpLlm(_base(server), token="rva-test-token")
        reply = client.complete("I need my bill")
        assert reply == "Ava at Acme Telco here."
        rec = store[-1]
        assert rec["path"] == "/v1/chat/completions"
        sent = json.loads(rec["body"])
        assert sent["messages"][0] == {"role": "user", "content": "I need my bill"}
        assert sent["model"] == "rva-llm"
        assert rec["ctype"].startswith("application/json")
        assert rec["auth"] == "Bearer rva-test-token"
    finally:
        server.shutdown()
        server.server_close()


def test_http_tts_resamples_24k_pcm_to_8k_frames() -> None:
    store: list[dict[str, object]] = []
    src = _tone_24k(2400)
    server = _start(_make_handler(store, tts_pcm=src))
    try:
        client = HttpTts(_base(server), token="rva-test-token")
        pcm = client.synthesize("hello")
        expected = resample_s16le(src, 24_000, 8_000)
        extra = len(expected) % 320
        if extra:
            expected = expected + b"\x00" * (320 - extra)
        assert pcm == expected
        assert len(pcm) % 320 == 0
        assert pcm != b"\x00" * len(pcm)
        sent = json.loads(store[-1]["body"])
        assert sent["input"] == "hello"
        assert sent["response_format"] == "pcm"
        assert sent["voice"] == "ava"
        assert store[-1]["path"] == "/v1/audio/speech"
    finally:
        server.shutdown()
        server.server_close()


def test_factory_http_turn_records_all_three_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    store: list[dict[str, object]] = []
    server = _start(_make_handler(store))
    base = _base(server)
    try:
        monkeypatch.setenv("RVA_STT_BACKEND", "http")
        monkeypatch.setenv("RVA_LLM_BACKEND", "http")
        monkeypatch.setenv("RVA_TTS_BACKEND", "http")
        monkeypatch.setenv("RVA_STT_URL", base)
        monkeypatch.setenv("RVA_LLM_URL", base)
        monkeypatch.setenv("RVA_TTS_URL", base)
        monkeypatch.setenv("RVA_STT_TOKEN", "rva-test-token")
        monkeypatch.setenv("RVA_LLM_TOKEN", "rva-test-token")
        monkeypatch.setenv("RVA_TTS_TOKEN", "rva-test-token")
        result = build_pipeline().turn(b"\x00\x00" * 160, sample_rate=16_000)
        assert result.user_text == "I need my bill"
        assert result.agent_text == "Ava at Acme Telco here."
        assert len(result.tts_pcm) % 320 == 0
        paths = [rec["path"] for rec in store]
        assert paths == [
            "/v1/audio/transcriptions",
            "/v1/chat/completions",
            "/v1/audio/speech",
        ]
        for rec in store:
            assert rec["auth"] == "Bearer rva-test-token"
        assert b"RIFF" in store[0]["body"]
        assert json.loads(store[1]["body"])["messages"][0]["content"] == "I need my bill"
        assert json.loads(store[2]["body"])["input"] == result.agent_text
    finally:
        server.shutdown()
        server.server_close()


def test_http_error_includes_body_prefix() -> None:
    store: list[dict[str, object]] = []
    server = _start(_make_handler(store))
    try:
        client = HttpLlm(_base(server) + "/missing", token="rva-test-token")
        with pytest.raises(BackendError, match="unknown-route"):
            client.complete("hi")
    finally:
        server.shutdown()
        server.server_close()


def test_http_redirect_is_rejected() -> None:
    store: list[dict[str, object]] = []
    server = _start(_make_handler(store, completions="redirect"))
    try:
        client = HttpLlm(_base(server), token="rva-test-token")
        with pytest.raises(BackendError, match="redirect"):
            client.complete("hi")
    finally:
        server.shutdown()
        server.server_close()


def test_invalid_json_and_stt_non_object_are_backend_error() -> None:
    store: list[dict[str, object]] = []
    server = _start(_make_handler(store, completions="badjson", stt_payload=[1]))
    try:
        with pytest.raises(BackendError, match="JSON"):
            HttpLlm(_base(server), token="rva-test-token").complete("hi")
        with pytest.raises(BackendError, match="missing text"):
            HttpStt(_base(server), token="rva-test-token").transcribe(b"\x00\x00")
    finally:
        server.shutdown()
        server.server_close()


def test_invalid_utf8_json_is_backend_error() -> None:
    store: list[dict[str, object]] = []
    server = _start(_make_handler(store, completions="badutf"))
    try:
        with pytest.raises(BackendError, match="JSON"):
            HttpLlm(_base(server), token="rva-test-token").complete("hi")
    finally:
        server.shutdown()
        server.server_close()


def test_bad_timeout_env_is_backend_error(monkeypatch: pytest.MonkeyPatch) -> None:
    store: list[dict[str, object]] = []
    server = _start(_make_handler(store))
    try:
        monkeypatch.setenv("RVA_HTTP_TIMEOUT", "nope")
        with pytest.raises(BackendError, match="RVA_HTTP_TIMEOUT"):
            HttpLlm(_base(server), token="rva-test-token").complete("hi")
    finally:
        server.shutdown()
        server.server_close()


def test_timeout_error_is_backend_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise TimeoutError("timed out")

    monkeypatch.setattr("rva.http_backends._OPENER.open", _boom)
    with pytest.raises(BackendError, match="timeout"):
        HttpLlm("http://127.0.0.1:9", token="rva-test-token").complete("hi")
