"""Per-stage p50/p95 samples and loopback /metrics JSON — no PII, no public net."""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Thread

import pytest

from rva.metrics import MetricsError, StageMetrics, percentile_ms, serve_metrics
from rva.pipeline import MockLlm, MockStt, MockTts, Pipeline, TurnResult

_LOOP = "127.0.0.1"


class _Clock:
    def __init__(self, marks: list[float]) -> None:
        self._marks = iter(marks)

    def __call__(self) -> float:
        return next(self._marks)


@contextmanager
def _running(server: ThreadingHTTPServer) -> Iterator[ThreadingHTTPServer]:
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def _get_json(host: str, port: int, path: str = "/metrics") -> tuple[int, object, str]:
    conn = HTTPConnection(host, port, timeout=2)
    conn.request("GET", path)
    resp = conn.getresponse()
    raw = resp.read()
    ctype = resp.getheader("Content-Type") or ""
    status = resp.status
    conn.close()
    body: object
    if "json" in ctype:
        body = json.loads(raw)
    else:
        body = raw
    return status, body, ctype


def test_percentile_nearest_rank_and_empty() -> None:
    assert percentile_ms([], 50) is None
    assert percentile_ms([10.0], 50) == 10.0
    assert percentile_ms([10.0], 95) == 10.0
    samples = [float(n) for n in range(1, 11)]
    assert percentile_ms(samples, 50) == 5.0
    assert percentile_ms(samples, 95) == 10.0
    with pytest.raises(MetricsError):
        percentile_ms(samples, 0)


def test_stage_metrics_p50_p95_from_known_ms() -> None:
    store = StageMetrics()
    for i in range(1, 21):
        store.record("stt", i / 1000.0)
    snap = store.snapshot()
    assert snap["stt"]["n"] == 20
    assert snap["stt"]["p50"] == 10.0
    assert snap["stt"]["p95"] == 19.0
    assert snap["llm"]["n"] == 0
    assert snap["llm"]["p50"] is None
    assert set(snap) == {"stt", "llm", "tts", "total"}


def test_ring_buffer_drops_oldest() -> None:
    store = StageMetrics(max_samples=3)
    for seconds in (0.001, 0.002, 0.003, 0.004):
        store.record("llm", seconds)
    snap = store.snapshot()
    assert snap["llm"]["n"] == 3
    assert snap["llm"]["p50"] == 3.0
    assert snap["llm"]["p95"] == 4.0


def test_rejects_unknown_stage_and_bad_duration() -> None:
    store = StageMetrics()
    with pytest.raises(MetricsError, match="unknown stage"):
        store.record("vad", 0.01)
    with pytest.raises(MetricsError, match="finite"):
        store.record("stt", float("nan"))
    with pytest.raises(MetricsError, match="finite"):
        store.record("stt", float("inf"))
    with pytest.raises(MetricsError, match="finite"):
        store.record("stt", float("-inf"))
    with pytest.raises(MetricsError, match="finite"):
        store.record("stt", -0.1)


def test_pipeline_turn_without_metrics_still_fills_durations() -> None:
    clock = _Clock([1.0, 1.004, 1.014, 1.034])
    pcm = b"\x00\x00" * 160
    pipe = Pipeline(MockStt("hello"), MockLlm(), MockTts(), clock=clock)
    assert pipe.metrics is None
    result = pipe.turn(pcm)
    assert isinstance(result, TurnResult)
    assert result.stt_s == pytest.approx(0.004)
    assert result.llm_s == pytest.approx(0.010)
    assert result.tts_s == pytest.approx(0.020)
    assert result.total_s == pytest.approx(0.034)


def test_pipeline_turn_records_four_stages_without_pii() -> None:
    store = StageMetrics()
    clock = _Clock([0.0, 0.010, 0.030, 0.080])
    pcm = b"\x00\x00" * 160
    result = Pipeline(
        MockStt("I need my bill"),
        MockLlm(),
        MockTts(),
        metrics=store,
        clock=clock,
    ).turn(pcm, sample_rate=16_000)
    assert result.user_text == "I need my bill"
    assert result.stt_s == pytest.approx(0.010)
    assert result.llm_s == pytest.approx(0.020)
    assert result.tts_s == pytest.approx(0.050)
    assert result.total_s == pytest.approx(0.080)
    snap = store.snapshot()
    assert snap["stt"]["p50"] == pytest.approx(10.0)
    assert snap["llm"]["p50"] == pytest.approx(20.0)
    assert snap["tts"]["p50"] == pytest.approx(50.0)
    assert snap["total"]["p50"] == pytest.approx(80.0)
    dumped = json.dumps(snap)
    assert "bill" not in dumped
    assert "I need" not in dumped
    assert "Acme" not in dumped


def test_metrics_http_json_on_loopback() -> None:
    store = StageMetrics()
    store.record("stt", 0.004)
    store.record("stt", 0.012)
    store.record("llm", 0.020)
    store.record("tts", 0.008)
    store.record("total", 0.040)
    server = serve_metrics(store, host=_LOOP, port=0)
    with _running(server):
        port = server.server_address[1]
        status, body, ctype = _get_json(_LOOP, port)
        assert status == 200
        assert "json" in ctype
        assert isinstance(body, dict)
        assert body["stt"]["n"] == 2
        assert body["stt"]["p50"] == pytest.approx(4.0)
        assert body["stt"]["p95"] == pytest.approx(12.0)
        assert body["total"]["p50"] == pytest.approx(40.0)
        assert "user_text" not in json.dumps(body)
        missing, _, _ = _get_json(_LOOP, port, "/secret")
        assert missing == 404


def test_metrics_http_empty_store_json_nulls() -> None:
    server = serve_metrics(StageMetrics(), host=_LOOP, port=0)
    with _running(server):
        status, body, _ = _get_json(_LOOP, server.server_address[1])
        assert status == 200
        assert isinstance(body, dict)
        for stage in ("stt", "llm", "tts", "total"):
            assert body[stage]["n"] == 0
            assert body[stage]["p50"] is None
            assert body[stage]["p95"] is None
        raw = json.dumps(body)
        assert "null" in raw


def test_metrics_http_binds_ipv6_loopback() -> None:
    store = StageMetrics()
    store.record("total", 0.005)
    server = serve_metrics(store, host="::1", port=0)
    assert server.address_family == socket.AF_INET6
    with _running(server):
        port = server.server_address[1]
        status, body, _ = _get_json("::1", port)
        assert status == 200
        assert isinstance(body, dict)
        assert body["total"]["n"] == 1
        assert body["total"]["p50"] == pytest.approx(5.0)


def test_metrics_http_binds_localhost_ipv4() -> None:
    server = serve_metrics(StageMetrics(), host="localhost", port=0)
    assert server.address_family == socket.AF_INET
    with _running(server):
        status, body, _ = _get_json("127.0.0.1", server.server_address[1])
        assert status == 200
        assert isinstance(body, dict)
        assert body["stt"]["n"] == 0
        assert body["stt"]["p50"] is None


def test_metrics_server_rejects_non_loopback() -> None:
    with pytest.raises(MetricsError, match="loopback"):
        serve_metrics(StageMetrics(), host="0.0.0.0", port=0)
