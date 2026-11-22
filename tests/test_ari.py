"""ARI hook: StasisStart starts CallSession. Fake HTTP only, no Asterisk."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from rva.ari import AriApp, AriClient, AriError
from rva.session import CallSession

_LOOP = "127.0.0.1"
_AUDIO_UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


class _Store:
    def __init__(self) -> None:
        self.gets: list[str] = []
        self.posts: list[str] = []


def _server(store: _Store, *, info: str = "ok") -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _fmt: str, *_args: object) -> None:
            return

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            store.gets.append(path)
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Basic "):
                self._raw(401, b"{}", "application/json")
                return
            if path == "/ari/asterisk/info":
                if info == "gone":
                    self._raw(404, b'{"error":"no"}', "application/json")
                    return
                if info == "badjson":
                    self._raw(200, b"{not-json", "application/json")
                    return
                self._raw(
                    200, json.dumps({"system": {"version": "20"}}).encode(), "application/json"
                )
                return
            self._raw(404, b"{}", "application/json")

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            store.posts.append(self.path)
            if path.startswith("/ari/channels/") and path.endswith("/continue"):
                self.send_response(204)
                self.end_headers()
                return
            self._raw(404, b"{}", "application/json")

        def _raw(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer((_LOOP, 0), Handler)


def _stasis_start(channel_id: str = "ch-1") -> dict[str, object]:
    return {
        "type": "StasisStart",
        "application": "rva",
        "args": [_AUDIO_UUID],
        "channel": {"id": channel_id, "state": "Up"},
    }


def test_stasis_start_creates_call_session_and_continues() -> None:
    posts: list[tuple[str, str, str]] = []

    class Rest:
        def continue_channel(self, channel_id: str, context: str, exten: str) -> None:
            posts.append((channel_id, context, exten))

    app = AriApp(rest=Rest())
    session = app.handle_event(_stasis_start("chan-ava"))
    assert isinstance(session, CallSession)
    assert app.sessions["chan-ava"] is session
    assert posts == [("chan-ava", "audiosocket", "s")]
    app.handle_event({"type": "StasisEnd", "channel": {"id": "chan-ava"}})
    assert "chan-ava" not in app.sessions


def test_unknown_event_is_ignored() -> None:
    app = AriApp()
    assert app.handle_event({"type": "ChannelStateChange"}) is None
    assert app.sessions == {}


def test_stasis_start_without_channel_is_error() -> None:
    app = AriApp()
    with pytest.raises(AriError, match="channel"):
        app.handle_event({"type": "StasisStart"})


def test_register_hits_asterisk_info_and_returns_events_url() -> None:
    store = _Store()
    server = _server(store)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        client = AriClient(f"http://{_LOOP}:{port}", "rva", "rva-ari-demo")
        url = client.register()
        assert store.gets == ["/ari/asterisk/info"]
        assert "app=rva" in url
        assert url.startswith(f"http://{_LOOP}:{port}/ari/events?")
        client.continue_channel("chan-1", "audiosocket", "s")
        assert any("/ari/channels/chan-1/continue" in p for p in store.posts)
        assert "context=audiosocket" in store.posts[0]
    finally:
        server.shutdown()
        server.server_close()


def test_register_requires_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RVA_ARI_URL", raising=False)
    with pytest.raises(AriError, match="RVA_ARI_URL"):
        AriClient.from_env()


def test_from_env_reads_rva_ari(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RVA_ARI_URL", "http://127.0.0.1:8088")
    monkeypatch.setenv("RVA_ARI_USER", "rva")
    monkeypatch.setenv("RVA_ARI_PASSWORD", "rva-ari-demo")
    monkeypatch.setenv("RVA_ARI_APP", "rva")
    client = AriClient.from_env()
    assert client.base_url == "http://127.0.0.1:8088"
    assert client.app == "rva"
    assert "app=rva" in client.events_url()


def test_register_http_error_includes_status() -> None:
    store = _Store()
    server = _server(store, info="gone")
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        client = AriClient(f"http://{_LOOP}:{port}", "rva", "rva-ari-demo")
        with pytest.raises(AriError, match="HTTP 404"):
            client.register()
    finally:
        server.shutdown()
        server.server_close()


def test_register_bad_json_is_ari_error() -> None:
    store = _Store()
    server = _server(store, info="badjson")
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        client = AriClient(f"http://{_LOOP}:{port}", "rva", "rva-ari-demo")
        with pytest.raises(AriError, match="JSON"):
            client.register()
    finally:
        server.shutdown()
        server.server_close()
