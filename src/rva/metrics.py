"""In-memory per-stage latency samples and a loopback dashboard JSON API.

Stores STT, LLM, TTS, and total durations only. No transcripts, PCM, or tokens.
"""

from __future__ import annotations

import json
import math
import socket
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STAGES: tuple[str, ...] = ("stt", "llm", "tts", "total")
_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})


class MetricsError(ValueError):
    """Invalid stage name, sample, or listen address."""


def percentile_ms(samples: list[float], pct: float) -> float | None:
    """Nearest-rank percentile. ``pct`` is in (0, 100]. Empty input is ``None``."""
    if pct <= 0 or pct > 100:
        raise MetricsError("percentile must be in (0, 100]")
    if not samples:
        return None
    ordered = sorted(samples)
    rank = math.ceil(pct / 100.0 * len(ordered))
    return ordered[min(max(rank, 1), len(ordered)) - 1]


class StageMetrics:
    """Bounded in-memory samples per pipeline stage, in milliseconds."""

    def __init__(self, max_samples: int = 256) -> None:
        if max_samples < 1:
            raise MetricsError("max_samples must be positive")
        self._lock = threading.Lock()
        self._samples: dict[str, deque[float]] = {
            name: deque(maxlen=max_samples) for name in STAGES
        }

    def record(self, stage: str, seconds: float) -> None:
        if stage not in self._samples:
            raise MetricsError(f"unknown stage {stage!r}")
        if seconds < 0 or seconds != seconds or math.isinf(seconds):
            raise MetricsError("duration must be a finite non-negative number")
        with self._lock:
            self._samples[stage].append(seconds * 1000.0)

    def snapshot(self) -> dict[str, dict[str, float | int | None]]:
        with self._lock:
            copied = {name: list(values) for name, values in self._samples.items()}
        return {
            name: {
                "n": len(copied[name]),
                "p50": percentile_ms(copied[name], 50),
                "p95": percentile_ms(copied[name], 95),
            }
            for name in STAGES
        }


class _LoopbackServer(ThreadingHTTPServer):
    """Threading HTTP server with an explicit IPv4 or IPv6 family."""

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler: type[BaseHTTPRequestHandler],
        family: int,
    ) -> None:
        self.address_family = family
        super().__init__(server_address, request_handler)


def _listen_family(host: str) -> int:
    if host == "::1":
        return socket.AF_INET6
    return socket.AF_INET


def serve_metrics(
    metrics: StageMetrics, host: str = "127.0.0.1", port: int = 0
) -> ThreadingHTTPServer:
    """Bind ``GET /metrics`` on loopback. ``port=0`` lets the OS pick a free port.

    ``::1`` uses IPv6. ``127.0.0.1`` and ``localhost`` use IPv4.
    """
    if host not in _LOOPBACK:
        raise MetricsError("dashboard metrics API binds loopback only")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _fmt: str, *_args: object) -> None:
            return

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path != "/metrics":
                self.send_error(404)
                return
            body = json.dumps(metrics.snapshot(), separators=(",", ":")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _LoopbackServer((host, port), Handler, _listen_family(host))
