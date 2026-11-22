"""CLI dialer originate: structured errors without tracebacks."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from threading import Thread

import pytest

from rva.cli import main

_LOOP = "127.0.0.1"


def test_dialer_originate_reports_missing_ari_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_path = tmp_path / "ok.csv"
    csv_path.write_text("msisdn,name\n+57 300 000 0001,x\n", encoding="utf-8")
    monkeypatch.delenv("RVA_ARI_URL", raising=False)
    monkeypatch.setenv("RVA_ARI_USER", "rva")
    monkeypatch.setenv("RVA_ARI_PASSWORD", "rva-ari-demo")
    out = StringIO()
    monkeypatch.setattr("sys.stdout", out)
    code = main(["dialer", "originate", "--csv", str(csv_path)])
    assert code == 1
    payload = json.loads(out.getvalue())
    assert "error" in payload
    assert payload["originated"] == []
    assert payload["jobs"] == []
    assert "RVA_ARI_URL" in payload["error"]


def _fail_one_server() -> ThreadingHTTPServer:
    posts: list[str] = []
    channel = iter(["c1", "c2"])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _fmt: str, *_args: object) -> None:
            return

        def do_GET(self) -> None:
            body = json.dumps({"system": {"version": "20"}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            posts.append(self.path)
            path = self.path.split("?", 1)[0]
            if path == "/ari/channels" and len(posts) == 1:
                self.send_response(500)
                self.end_headers()
                return
            if path == "/ari/channels":
                body = json.dumps({"id": next(channel, "cz"), "state": "Down"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

    return ThreadingHTTPServer((_LOOP, 0), Handler)


def test_cli_partial_failure_includes_job_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_path = tmp_path / "two.csv"
    csv_path.write_text(
        "msisdn,name\n+57 300 000 0001,A\n+57 300 000 0002,B\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RVA_DIALER_MAX_RETRIES", "1")
    monkeypatch.setenv("RVA_ARI_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("RVA_ARI_USER", "rva")
    monkeypatch.setenv("RVA_ARI_PASSWORD", "rva-ari-demo")
    server = _fail_one_server()
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    monkeypatch.setenv("RVA_ARI_URL", f"http://{_LOOP}:{port}")
    out = StringIO()
    monkeypatch.setattr("sys.stdout", out)
    try:
        code = main(["dialer", "originate", "--csv", str(csv_path)])
    finally:
        server.shutdown()
        server.server_close()
    assert code == 1
    payload = json.loads(out.getvalue())
    assert len(payload["jobs"]) == 2
    assert len(payload["originated"]) == 1
    states = {row["state"] for row in payload["jobs"]}
    assert "failed" in states and "done" in states
