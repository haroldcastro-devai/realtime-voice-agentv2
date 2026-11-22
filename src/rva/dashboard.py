"""Loopback status panel: active calls, latency p50/p95, Colab health."""

from __future__ import annotations

import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from rva.call_activity import REGISTRY
from rva.colab import ColabOrchestrator
from rva.metrics import LoopbackServer, StageMetrics, listen_family
from rva.transcript_feed import TRANSCRIPT_FEED

_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})
_PANEL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Ava / Acme Telco — local dashboard</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 1.5rem; }
    table { border-collapse: collapse; }
    td, th { border: 1px solid #ccc; padding: 0.35rem 0.75rem; }
    #status_error { color: #a00; }
  </style>
</head>
<body>
  <h1>Ava agent (loopback)</h1>
  <p id="status_error"></p>
  <p>Active calls: <span id="active_calls">—</span></p>
  <p>Colab: <span id="colab_status">—</span> (RTT <span id="colab_rtt">—</span> ms)</p>
  <h2>Latency (ms)</h2>
  <table>
    <thead><tr><th>Stage</th><th>n</th><th>p50</th><th>p95</th></tr></thead>
    <tbody id="latency_body"></tbody>
  </table>
  <h2>Live transcript</h2>
  <ul id="transcript_list"></ul>
  <script>
    function authHeaders() {
      const token = new URLSearchParams(location.search).get("token");
      if (!token) return {};
      return { Authorization: "Bearer " + token };
    }
    function setText(id, value) {
      const el = document.getElementById(id);
      if (el) el.textContent = value;
    }
    function renderLatency(stages) {
      const body = document.getElementById("latency_body");
      if (!body) return;
      body.textContent = "";
      for (const [stage, row] of Object.entries(stages)) {
        const tr = document.createElement("tr");
        for (const cell of [stage, row.n, row.p50, row.p95]) {
          const td = document.createElement("td");
          td.textContent = cell == null ? "—" : String(cell);
          tr.appendChild(td);
        }
        body.appendChild(tr);
      }
    }
    function renderTranscript(lines) {
      const root = document.getElementById("transcript_list");
      if (!root) return;
      root.textContent = "";
      for (const row of lines) {
        const li = document.createElement("li");
        const label = document.createElement("strong");
        label.textContent = row.role + ": ";
        li.appendChild(label);
        const span = document.createElement("span");
        span.textContent = row.text;
        li.appendChild(span);
        root.appendChild(li);
      }
    }
    async function refresh() {
      try {
        const res = await fetch("/api/dashboard", { headers: authHeaders() });
        if (!res.ok) {
          setText("status_error", "Dashboard API error: " + res.status);
          return;
        }
        const data = await res.json();
        setText("status_error", "");
        setText("active_calls", String(data.active_calls));
        setText("colab_status", data.colab.status);
        setText("colab_rtt", data.colab.rtt_ms == null ? "—" : String(data.colab.rtt_ms));
        renderLatency(data.latency_ms);
        renderTranscript(data.transcript || []);
      } catch (err) {
        setText("status_error", "Fetch failed");
      }
    }
    refresh();
    setInterval(refresh, 2000);
  </script>
</body>
</html>
"""


class DashboardError(ValueError):
    """Invalid dashboard listen address."""


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "" or raw == "CHANGE_ME":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise DashboardError(f"{name} must be an integer") from exc


def dashboard_host() -> str:
    return os.environ.get("RVA_DASHBOARD_HOST") or "127.0.0.1"


def dashboard_port() -> int:
    return _env_int("RVA_DASHBOARD_PORT", 8765)


def configured_dashboard_token() -> str | None:
    raw = os.environ.get("RVA_DASHBOARD_TOKEN")
    if raw is None or raw == "" or raw == "CHANGE_ME":
        return None
    return raw


def dashboard_token_required() -> bool:
    return configured_dashboard_token() is not None


def _token_from_headers(headers: object) -> str | None:
    auth = headers.get("Authorization") if hasattr(headers, "get") else None
    if not auth or not auth.startswith("Bearer "):
        return None
    return auth[7:].strip() or None


def _token_from_path(raw_path: str) -> str | None:
    parsed = urlparse(raw_path)
    values = parse_qs(parsed.query).get("token")
    if not values:
        return None
    return values[0] or None


def is_dashboard_authorized(headers: object, raw_path: str) -> bool:
    expected = configured_dashboard_token()
    if expected is None:
        return True
    provided = _token_from_headers(headers) or _token_from_path(raw_path)
    if provided is None:
        return False
    return secrets.compare_digest(provided, expected)


def dashboard_metrics(metrics: StageMetrics | None = None) -> StageMetrics:
    return metrics if metrics is not None else StageMetrics.shared()


def build_dashboard_snapshot(metrics: StageMetrics) -> dict[str, object]:
    colab = ColabOrchestrator.shared().peek_status()
    if not colab.configured:
        colab_label = "DOWN"
    elif colab.health_ok:
        colab_label = "UP"
    else:
        colab_label = "DOWN"
    return {
        "active_calls": REGISTRY.count(),
        "colab": {
            "status": colab_label,
            "configured": colab.configured,
            "health_ok": colab.health_ok,
            "rtt_ms": colab.rtt_ms,
            "fallback_stt_tts": colab.fallback_stt_tts,
            "in_call": colab.in_call,
        },
        "latency_ms": metrics.snapshot(),
        "transcript": TRANSCRIPT_FEED.snapshot(),
    }


def dashboard_url(host: str, port: int) -> str:
    if host == "::1":
        return f"http://[::1]:{port}/"
    return f"http://{host}:{port}/"


def serve_dashboard(
    metrics: StageMetrics | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
) -> ThreadingHTTPServer:
    store = dashboard_metrics(metrics)
    bind = host if host is not None else dashboard_host()
    listen_port = port if port is not None else dashboard_port()
    if bind not in _LOOPBACK:
        raise DashboardError("dashboard binds loopback only")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _fmt: str, *_args: object) -> None:
            return

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html", "/api/dashboard", "/metrics"):
                if not is_dashboard_authorized(self.headers, self.path):
                    self._send(401, b"unauthorized", "text/plain; charset=utf-8")
                    return
            if path in ("/", "/index.html"):
                body = _PANEL_HTML.encode("utf-8")
                self._send(200, body, "text/html; charset=utf-8")
                return
            if path == "/api/dashboard":
                payload = build_dashboard_snapshot(store)
                body = json.dumps(payload, separators=(",", ":")).encode()
                self._send(200, body, "application/json; charset=utf-8")
                return
            if path == "/metrics":
                body = json.dumps(store.snapshot(), separators=(",", ":")).encode()
                self._send(200, body, "application/json; charset=utf-8")
                return
            self.send_error(404)

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    try:
        return LoopbackServer((bind, listen_port), Handler, listen_family(bind))
    except OSError as exc:
        raise DashboardError(str(exc)) from exc


def shutdown_server(server: ThreadingHTTPServer) -> None:
    """Stop a threaded dashboard server without deadlocking the caller."""
    thread = threading.Thread(target=server.shutdown, daemon=True)
    thread.start()
    thread.join(timeout=5.0)
    server.server_close()
