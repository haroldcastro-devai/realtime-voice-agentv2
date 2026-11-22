"""Loopback dashboard JSON and HTML — no PII, no public bind."""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection

import pytest

from rva.ari import AriApp
from rva.call_activity import REGISTRY
from rva.colab import ColabOrchestrator
from rva.dashboard import (
    DashboardError,
    build_dashboard_snapshot,
    dashboard_url,
    is_dashboard_authorized,
    serve_dashboard,
    shutdown_server,
)
from rva.metrics import StageMetrics
from rva.pipeline import build_pipeline
from rva.transcript_feed import TRANSCRIPT_FEED

_LOOP = "127.0.0.1"


def _get(
    path: str, port: int, headers: dict[str, str] | None = None
) -> tuple[int, bytes]:
    conn = HTTPConnection(_LOOP, port, timeout=5)
    try:
        conn.request("GET", path, headers=headers or {})
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


class _Hdr(dict):
    def get(self, key: str, default: str | None = None) -> str | None:  # type: ignore[override]
        return super().get(key, default)


def test_build_snapshot_includes_calls_colab_and_latency() -> None:
    ColabOrchestrator.reset_shared_for_tests()
    StageMetrics.reset_shared_for_tests()
    REGISTRY.reset_for_tests()
    metrics = StageMetrics.shared()
    metrics.record("total", 0.5)
    REGISTRY.on_stasis_start("ch-1")
    snap = build_dashboard_snapshot(metrics)
    assert snap["active_calls"] == 1
    assert "colab" in snap
    assert snap["colab"]["status"] in ("UP", "DOWN")
    assert "latency_ms" in snap
    assert snap["latency_ms"]["total"]["n"] == 1


def test_shared_metrics_visible_to_dashboard_and_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RVA_RECORD_LATENCY", "1")
    ColabOrchestrator.reset_shared_for_tests()
    StageMetrics.reset_shared_for_tests()
    pipe = build_pipeline()
    assert pipe.metrics is StageMetrics.shared()
    pipe.turn(b"\x00" * 320, sample_rate=16_000)
    snap = build_dashboard_snapshot(StageMetrics.shared())
    assert snap["latency_ms"]["total"]["n"] >= 1


def test_peek_status_does_not_increment_colab_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    ColabOrchestrator.reset_shared_for_tests()
    monkeypatch.setenv("RVA_COLAB_URL", "http://127.0.0.1:9")
    orch = ColabOrchestrator.shared()
    before = orch.refresh().consecutive_failures
    orch.peek_status()
    after = orch.peek_status()
    assert after.consecutive_failures == before


def test_dashboard_api_on_loopback() -> None:
    ColabOrchestrator.reset_shared_for_tests()
    StageMetrics.reset_shared_for_tests()
    REGISTRY.reset_for_tests()
    metrics = StageMetrics.shared()
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
        shutdown_server(server)


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
        assert "status_error" in text
        assert "Fetch failed" in text
    finally:
        shutdown_server(server)


def test_dashboard_url_ipv6_literal() -> None:
    assert dashboard_url("::1", 8765) == "http://[::1]:8765/"


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


def test_active_call_registry_concurrent_updates() -> None:
    REGISTRY.reset_for_tests()
    barrier = threading.Barrier(3)

    def worker(prefix: str) -> None:
        barrier.wait()
        for i in range(50):
            ch = f"{prefix}-{i}"
            REGISTRY.on_stasis_start(ch)
            REGISTRY.on_stasis_end(ch)

    threads = [threading.Thread(target=worker, args=(f"t{n}",)) for n in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert REGISTRY.count() == 0


def test_snapshot_includes_transcript_lines() -> None:
    TRANSCRIPT_FEED.reset_for_tests()
    StageMetrics.reset_shared_for_tests()
    TRANSCRIPT_FEED.record_turn("hola", "Ava reply")
    snap = build_dashboard_snapshot(StageMetrics.shared())
    assert snap["transcript"] == [
        {"role": "user", "text": "hola"},
        {"role": "agent", "text": "Ava reply"},
    ]


def test_pipeline_records_transcript_when_env_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    TRANSCRIPT_FEED.reset_for_tests()
    monkeypatch.setenv("RVA_DASHBOARD_TRANSCRIPT", "1")
    pipe = build_pipeline()
    pipe.turn(b"\x00" * 320, sample_rate=16_000)
    lines = TRANSCRIPT_FEED.snapshot()
    assert len(lines) == 2
    assert lines[0]["role"] == "user"
    assert lines[1]["role"] == "agent"


def test_dashboard_token_optional_by_default() -> None:
    server = serve_dashboard(StageMetrics(), host=_LOOP, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        code, _ = _get("/api/dashboard", port)
        assert code == 200
    finally:
        shutdown_server(server)


def test_dashboard_token_rejects_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RVA_DASHBOARD_TOKEN", "local-dev-token")
    server = serve_dashboard(StageMetrics(), host=_LOOP, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        code, _ = _get("/api/dashboard", port)
        assert code == 401
    finally:
        shutdown_server(server)
    monkeypatch.delenv("RVA_DASHBOARD_TOKEN", raising=False)


def test_dashboard_token_accepts_bearer_and_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RVA_DASHBOARD_TOKEN", "local-dev-token")
    server = serve_dashboard(StageMetrics(), host=_LOOP, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        code, _ = _get(
            "/api/dashboard",
            port,
            headers={"Authorization": "Bearer local-dev-token"},
        )
        assert code == 200
        code2, _ = _get("/api/dashboard?token=local-dev-token", port)
        assert code2 == 200
    finally:
        shutdown_server(server)
    monkeypatch.delenv("RVA_DASHBOARD_TOKEN", raising=False)


def test_is_dashboard_authorized_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RVA_DASHBOARD_TOKEN", "abc")
    headers = _Hdr({"Authorization": "Bearer abc"})
    assert is_dashboard_authorized(headers, "/api/dashboard")
    assert not is_dashboard_authorized(_Hdr({}), "/api/dashboard?token=wrong")


def test_dashboard_html_transcript_uses_text_content_only() -> None:
    server = serve_dashboard(StageMetrics(), host=_LOOP, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        code, body = _get("/", port)
        assert code == 200
        text = body.decode("utf-8")
        assert "renderTranscript" in text
        assert "transcript_list" in text
        assert "innerHTML" not in text
    finally:
        shutdown_server(server)


def test_transcript_xss_payload_round_trips_as_plain_text() -> None:
    payload = "<img src=x onerror=alert(1)>"
    TRANSCRIPT_FEED.reset_for_tests()
    TRANSCRIPT_FEED.record_turn(payload, "ok")
    snap = build_dashboard_snapshot(StageMetrics())
    assert snap["transcript"][0]["text"] == payload
