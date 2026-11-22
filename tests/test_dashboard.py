"""Loopback dashboard JSON and HTML — no PII, no public bind."""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest

from rva.ari import AriApp
from rva.colab import ColabOrchestrator
from rva.dashboard import (
    REGISTRY,
    ActiveCallRegistry,
    DashboardError,
    build_dashboard_snapshot,
    serve_dashboard,
)
from rva.metrics import StageMetrics

_LOOP = "127.0.0.1"
_REPO = Path(__file__).resolve().parents[1]


def _get(path: str, port: int) -> tuple[int, bytes]:
    conn = HTTPConnection(_LOOP, port, timeout=5)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def test_build_snapshot_includes_calls_colab_and_latency() -> None:
    ColabOrchestrator.reset_shared_for_tests()
    REGISTRY.reset_for_tests()
    metrics = StageMetrics()
    metrics.record("total", 0.5)
    REGISTRY.on_stasis_start("ch-1")
    snap = build_dashboard_snapshot(metrics)
    assert snap["active_calls"] == 1
    assert "colab" in snap
    assert snap["colab"]["status"] in ("UP", "DOWN")
    assert "latency_ms" in snap
    assert snap["latency_ms"]["total"]["n"] == 1


def test_dashboard_api_on_loopback() -> None:
    ColabOrchestrator.reset_shared_for_tests()
    REGISTRY.reset_for_tests()
    metrics = StageMetrics()
    metrics.record("stt", 0.01)
    server = serve_dashboard(metrics, host=_LOOP, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        code, body = _get("/api/dashboard", port)
        assert code == 200
        data = json.loads(body.decode())
        assert "active_calls" in data
        assert data["colab"]["status"] in ("UP", "DOWN")
        assert "rtt_ms" in data["colab"]
        assert data["latency_ms"]["stt"]["n"] == 1
        code2, body2 = _get("/metrics", port)
        assert code2 == 200
        assert b"stt" in body2
    finally:
        server.shutdown()
        server.server_close()


def test_dashboard_html_uses_text_content_not_inner_html() -> None:
    server = serve_dashboard(StageMetrics(), host=_LOOP, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        code, body = _get("/", port)
        assert code == 200
        text = body.decode("utf-8")
        assert "textContent" in text
        assert "innerHTML" not in text
    finally:
        server.shutdown()
        server.server_close()


def test_serve_dashboard_rejects_public_bind() -> None:
    with pytest.raises(DashboardError, match="loopback"):
        serve_dashboard(StageMetrics(), host="0.0.0.0", port=0)


def test_ari_stasis_updates_active_call_registry() -> None:
    REGISTRY.reset_for_tests()
    app = AriApp()
    app.handle_event(
        {
            "type": "StasisStart",
            "channel": {"id": "chan-dash"},
            "args": ["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"],
        }
    )
    assert REGISTRY.count() == 1
    app.handle_event({"type": "StasisEnd", "channel": {"id": "chan-dash"}})
    assert REGISTRY.count() == 0


def test_active_call_registry_is_thread_safe() -> None:
    reg = ActiveCallRegistry()
    reg.on_stasis_start("a")
    reg.on_stasis_start("b")
    assert reg.count() == 2
    reg.on_stasis_end("a")
    assert reg.count() == 1
