"""OpenAI-compatible HTTP mapping against a local fake server — no public net."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from rva.http_backends import HttpLlm, HttpStt, HttpTts
from rva.pipeline import BackendError, build_pipeline

_LOOP = "127.0.0.1"


class _FakeOpenAI(BaseHTTPRequestHandler):
    last_path = ""
    last_body = b""
    last_ctype = ""
    last_auth = ""
    stt_text = "I need my bill"
    llm_text = "Ava at Acme Telco here."
    tts_pcm = b"\x00\x00" * 50

    def log_message(self, _fmt: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        type(self).last_path = self.path
        type(self).last_body = self.rfile.read(length)
        type(self).last_ctype = self.headers.get("Content-Type", "")
        type(self).last_auth = self.headers.get("Authorization", "")
        route = self.path.split("?", 1)[0]
        if route == "/v1/audio/transcriptions":
            self._json(200, {"text": self.stt_text})
            return
        if route == "/v1/chat/completions":
            self._json(
                200,
                {"choices": [{"message": {"role": "assistant", "content": self.llm_text}}]},
            )
            return
        if route == "/v1/audio/speech":
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(self.tts_pcm)))
            self.end_headers()
            self.wfile.write(self.tts_pcm)
            return
        self._json(404, {"error": "unknown"})

    def _json(self, code: int, payload: dict[str, object]) -> None:
        blob = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)


def _start() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((_LOOP, 0), _FakeOpenAI)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _base(server: ThreadingHTTPServer) -> str:
    return f"http://{_LOOP}:{server.server_address[1]}"


def test_http_stt_maps_multipart_and_json_text() -> None:
    server = _start()
    try:
        client = HttpStt(_base(server), token="rva-test-token", model="rva-stt")
        pcm = b"\x01\x00" * 8
        text = client.transcribe(pcm, sample_rate=16_000)
        assert text == "I need my bill"
        assert _FakeOpenAI.last_path.split("?", 1)[0] == "/v1/audio/transcriptions"
        assert "multipart/form-data" in _FakeOpenAI.last_ctype
        assert b"rva-stt" in _FakeOpenAI.last_body
        assert pcm in _FakeOpenAI.last_body
        assert _FakeOpenAI.last_auth == "Bearer rva-test-token"
    finally:
        server.shutdown()
        server.server_close()


def test_http_llm_maps_chat_completions() -> None:
    server = _start()
    try:
        client = HttpLlm(_base(server), token="rva-test-token")
        reply = client.complete("I need my bill")
        assert reply == "Ava at Acme Telco here."
        assert _FakeOpenAI.last_path.split("?", 1)[0] == "/v1/chat/completions"
        sent = json.loads(_FakeOpenAI.last_body.decode())
        assert sent["messages"][0] == {"role": "user", "content": "I need my bill"}
        assert sent["model"] == "rva-llm"
        assert _FakeOpenAI.last_ctype.startswith("application/json")
    finally:
        server.shutdown()
        server.server_close()


def test_http_tts_maps_speech_and_pads_20ms_frames() -> None:
    server = _start()
    try:
        client = HttpTts(_base(server), token="rva-test-token")
        pcm = client.synthesize("hello")
        assert len(pcm) % 320 == 0
        assert pcm.startswith(_FakeOpenAI.tts_pcm)
        sent = json.loads(_FakeOpenAI.last_body.decode())
        assert sent["input"] == "hello"
        assert sent["response_format"] == "pcm"
        assert sent["voice"] == "ava"
        assert _FakeOpenAI.last_path.split("?", 1)[0] == "/v1/audio/speech"
    finally:
        server.shutdown()
        server.server_close()


def test_factory_http_turn_against_fake_server(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _start()
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
    finally:
        server.shutdown()
        server.server_close()


def test_http_error_status_is_backend_error() -> None:
    server = _start()
    try:
        client = HttpLlm(_base(server) + "/missing", token="rva-test-token")
        with pytest.raises(BackendError, match="HTTP 404"):
            client.complete("hi")
    finally:
        server.shutdown()
        server.server_close()
