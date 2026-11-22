"""Colab orchestrator: fake /health server, backoff, in-call pin, CLI status."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from rva.cli import main as rva_main
from rva.colab import ColabOrchestrator, backoff_seconds, probe_colab_health
from rva.http_backends import HttpStt
from rva.pipeline import MockStt, build_pipeline

_LOOP = "127.0.0.1"


@pytest.fixture(autouse=True)
def _reset_colab_singleton() -> None:
    ColabOrchestrator.reset_shared_for_tests()
    yield
    ColabOrchestrator.reset_shared_for_tests()


class _HealthHandler(BaseHTTPRequestHandler):
    ok: bool = True
    status_code: int = 200

    def log_message(self, _fmt: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] != "/health":
            self.send_response(404)
            self.end_headers()
            return
        auth = self.headers.get("Authorization", "")
        if auth != "Bearer test-token":
            self.send_response(401)
            self.end_headers()
            return
        body = {"ok": "true" if self.ok else "false"}
        raw = json.dumps(body).encode()
        self.send_response(self.status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _server() -> tuple[ThreadingHTTPServer, Thread, type[_HealthHandler]]:
    _HealthHandler.ok = True
    _HealthHandler.status_code = 200
    handler = _HealthHandler
    server = ThreadingHTTPServer((_LOOP, 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, handler


def test_backoff_seconds_caps() -> None:
    assert backoff_seconds(0) == 0.0
    assert backoff_seconds(1) == 2.0
    assert backoff_seconds(3, cap_s=10.0) == 8.0
    assert backoff_seconds(10, cap_s=60.0) == 60.0


def test_probe_colab_health_ok_and_rtt(monkeypatch) -> None:
    server, _thread, handler = _server()
    base = f"http://{_LOOP}:{server.server_address[1]}"
    handler.ok = True
    try:
        ok, rtt = probe_colab_health(base, "test-token", 2.0)
        assert ok is True
        assert rtt is not None and rtt >= 0.0
    finally:
        server.shutdown()


def test_orchestrator_fallback_after_failure(monkeypatch) -> None:
    server, _thread, handler = _server()
    base = f"http://{_LOOP}:{server.server_address[1]}"
    monkeypatch.setenv("RVA_COLAB_URL", base)
    monkeypatch.setenv("RVA_COLAB_TOKEN", "test-token")
    monkeypatch.setenv("RVA_STT_BACKEND", "http")
    monkeypatch.setenv("RVA_TTS_BACKEND", "http")
    orch = ColabOrchestrator(clock=lambda: 0.0)
    handler.ok = False
    handler.status_code = 503
    try:
        snap = orch.refresh()
        assert snap.health_ok is False
        assert snap.consecutive_failures == 1
        assert snap.fallback_stt_tts is True
        pipe = build_pipeline(orchestrator=orch)
        assert isinstance(pipe.stt, MockStt)
    finally:
        server.shutdown()


def test_build_pipeline_keeps_http_stt_when_pinned(monkeypatch) -> None:
    server, _thread, handler = _server()
    base = f"http://{_LOOP}:{server.server_address[1]}"
    monkeypatch.setenv("RVA_COLAB_URL", base)
    monkeypatch.setenv("RVA_COLAB_TOKEN", "test-token")
    monkeypatch.setenv("RVA_STT_BACKEND", "http")
    monkeypatch.setenv("RVA_STT_URL", base)
    monkeypatch.setenv("RVA_TTS_BACKEND", "mock")
    orch = ColabOrchestrator.shared()
    orch.enter_call(remote_stt_tts=True)
    handler.ok = False
    handler.status_code = 503
    try:
        pipe = build_pipeline(orchestrator=orch)
        assert isinstance(pipe.stt, HttpStt)
    finally:
        server.shutdown()


def test_in_call_pins_http_despite_fallback(monkeypatch) -> None:
    server, _thread, handler = _server()
    base = f"http://{_LOOP}:{server.server_address[1]}"
    monkeypatch.setenv("RVA_COLAB_URL", base)
    monkeypatch.setenv("RVA_COLAB_TOKEN", "test-token")
    monkeypatch.setenv("RVA_STT_BACKEND", "http")
    monkeypatch.setenv("RVA_STT_URL", base)
    monkeypatch.setenv("RVA_TTS_BACKEND", "http")
    monkeypatch.setenv("RVA_TTS_URL", base)
    orch = ColabOrchestrator()
    handler.ok = True
    try:
        orch.refresh()
        orch.enter_call(remote_stt_tts=True)
        handler.ok = False
        handler.status_code = 503
        orch.refresh()
        assert orch.use_remote_stt_tts() is True
        snap = orch._status_snapshot(backoff_remaining_s=0.0)
        assert snap.pinned_remote is True
        assert snap.fallback_stt_tts is False
    finally:
        server.shutdown()


def test_cli_colab_status_json(monkeypatch, capsys) -> None:
    server, _thread, handler = _server()
    base = f"http://{_LOOP}:{server.server_address[1]}"
    monkeypatch.setenv("RVA_COLAB_URL", base)
    monkeypatch.setenv("RVA_COLAB_TOKEN", "test-token")
    handler.ok = True
    try:
        code = rva_main(["colab", "status"])
        assert code == 0
        out = json.loads(capsys.readouterr().out)
        assert out["health_ok"] is True
        assert "rtt_ms" in out
        assert "backoff_remaining_s" in out
    finally:
        server.shutdown()
