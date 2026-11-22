"""Fictional Acme campaign CSV and ARI originate (fake HTTP only)."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlparse

import pytest

from rva.ari import AriClient
from rva.dialer import (
    DialerError,
    build_endpoint,
    default_campaign_csv,
    is_fictional_acme_msisdn,
    load_acme_campaign,
    normalize_msisdn,
    originate_query,
    run_acme_campaign,
)

_LOOP = "127.0.0.1"
_REPO = Path(__file__).resolve().parents[1]


def test_bundled_csv_is_fictional_only() -> None:
    path = default_campaign_csv()
    contacts = load_acme_campaign(path)
    assert len(contacts) >= 2
    for contact in contacts:
        assert is_fictional_acme_msisdn(contact.msisdn)


def test_normalize_msisdn_accepts_spaced_colombia() -> None:
    assert normalize_msisdn("+57 300 000 0001") == "+573000000001"


def test_rejects_real_looking_msisdn(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("msisdn,name\n+57 301 234 5678,real\n", encoding="utf-8")
    with pytest.raises(DialerError, match="refusing non-fictional"):
        load_acme_campaign(bad)


def test_rejects_subscriber_dump(tmp_path: Path) -> None:
    bad = tmp_path / "dump.csv"
    bad.write_text("msisdn,name\n+15551234567,US\n", encoding="utf-8")
    with pytest.raises(DialerError, match="refusing non-fictional"):
        load_acme_campaign(bad)


def test_build_endpoint_default() -> None:
    assert build_endpoint("+573000000001") == "Local/573000000001@acme-campaign"


def test_originate_query_includes_app_args() -> None:
    q = originate_query("Local/x@acme-campaign", "rva", ["uuid-1", "uuid-2"])
    assert "endpoint=Local" in q
    assert "app=rva" in q
    assert q.count("appArgs=") == 2


class _Store:
    def __init__(self) -> None:
        self.posts: list[str] = []


def _server(store: _Store) -> ThreadingHTTPServer:
    channel_ids = iter(["chan-a", "chan-b", "chan-c"])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _fmt: str, *_args: object) -> None:
            return

        def do_GET(self) -> None:
            if self.path.startswith("/ari/asterisk/info"):
                body = json.dumps({"system": {"version": "20"}}).encode()
                self._raw(200, body)
                return
            self._raw(404, b"{}")

        def do_POST(self) -> None:
            store.posts.append(self.path)
            path = self.path.split("?", 1)[0]
            if path == "/ari/channels":
                chan = next(channel_ids, "chan-z")
                body = json.dumps({"id": chan, "state": "Down"}).encode()
                self._raw(200, body)
                return
            if path.endswith("/continue"):
                self.send_response(204)
                self.end_headers()
                return
            self._raw(404, b"{}")

        def _raw(self, code: int, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer((_LOOP, 0), Handler)


def test_run_acme_campaign_originates_each_contact(tmp_path: Path) -> None:
    csv_path = tmp_path / "mini.csv"
    csv_path.write_text(
        "msisdn,name\n+57 300 000 0001,A\n+57 300 000 0002,B\n",
        encoding="utf-8",
    )
    contacts = load_acme_campaign(csv_path)
    store = _Store()
    server = _server(store)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        client = AriClient(f"http://{_LOOP}:{port}", "rva", "rva-ari-demo")
        results = run_acme_campaign(client, contacts)
        assert len(results) == 2
        assert all(r.channel_id.startswith("chan-") for r in results)
        assert len(store.posts) == 2
        for post, contact in zip(store.posts, contacts, strict=True):
            assert post.startswith("/ari/channels?")
            qs = parse_qs(urlparse(post).query)
            assert qs["app"] == ["rva"]
            assert qs["endpoint"] == [build_endpoint(contact.msisdn)]
            assert qs["appArgs"]
    finally:
        server.shutdown()
        server.server_close()


def test_originate_channel_returns_id() -> None:
    store = _Store()
    server = _server(store)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        client = AriClient(f"http://{_LOOP}:{port}", "rva", "rva-ari-demo", app="rva")
        channel_id = client.originate_channel("Local/573000000001@acme-campaign", ["uuid"])
        assert channel_id == "chan-a"
    finally:
        server.shutdown()
        server.server_close()


def test_campaign_limit_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    csv_path = tmp_path / "many.csv"
    rows = ["msisdn,name"] + [f"+57 300 000 {i:04d},x" for i in range(1, 5)]
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    contacts = load_acme_campaign(csv_path)
    monkeypatch.setenv("RVA_DIALER_MAX_CONTACTS", "3")
    store = _Store()
    server = _server(store)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        client = AriClient(f"http://{_LOOP}:{port}", "rva", "rva-ari-demo")
        with pytest.raises(DialerError, match="limit"):
            run_acme_campaign(client, contacts)
    finally:
        server.shutdown()
        server.server_close()


def test_extensions_include_acme_campaign_context() -> None:
    text = (_REPO / "deploy" / "asterisk" / "etc" / "extensions.conf").read_text(encoding="utf-8")
    assert "[acme-campaign]" in text
    assert "57300000" in text
