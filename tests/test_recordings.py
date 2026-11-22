"""Optional recordings archive — off by default, fictional bucket, no network."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from rva.ari import AriApp
from rva.cli import main as rva_main
from rva.recordings import (
    CALL_BUFFER,
    DEFAULT_FICTIONAL_BUCKET,
    HttpMinioBackend,
    InMemoryRabbit,
    InMemoryRecordingBackend,
    RecordingArchive,
    RecordingError,
    recordings_enabled,
)

_LOOP = "127.0.0.1"


class _RecordingHttpHandler(BaseHTTPRequestHandler):
    puts: list[tuple[str, bytes]] = []
    posts: list[bytes] = []

    def log_message(self, _fmt: str, *_args: object) -> None:
        return

    def do_PUT(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        _RecordingHttpHandler.puts.append((self.path, body))
        self.send_response(204)
        self.end_headers()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        _RecordingHttpHandler.posts.append(body)
        self.send_response(204)
        self.end_headers()


def _start_http_server() -> tuple[ThreadingHTTPServer, int]:
    _RecordingHttpHandler.puts = []
    _RecordingHttpHandler.posts = []
    server = ThreadingHTTPServer((_LOOP, 0), _RecordingHttpHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return server, port


def test_recordings_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RVA_RECORDINGS_ENABLE", raising=False)
    RecordingArchive.reset_shared_for_tests()
    archive = RecordingArchive.shared()
    assert not recordings_enabled()
    assert not archive.enabled
    assert archive.archive_completed_call("ch-1", b"\x00" * 320) is None


def test_archive_stores_fictional_bucket_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RVA_RECORDINGS_ENABLE", "1")
    RecordingArchive.reset_shared_for_tests()
    minio = InMemoryRecordingBackend()
    rabbit = InMemoryRabbit()
    archive = RecordingArchive(enabled=True, minio=minio, rabbit=rabbit)
    pcm = b"\x00\x01" * 160
    stored = archive.archive_completed_call("chan-demo", pcm)
    assert stored is not None
    assert stored.bucket == DEFAULT_FICTIONAL_BUCKET
    assert stored.key == "calls/chan-demo.pcm"
    assert minio.objects[DEFAULT_FICTIONAL_BUCKET][stored.key] == pcm
    assert len(rabbit.messages) == 1
    msg = json.loads(rabbit.messages[0])
    assert msg["event"] == "call_recording_archived"
    assert msg["bucket"] == DEFAULT_FICTIONAL_BUCKET


def test_archive_empty_pcm_still_publishes_notice() -> None:
    minio = InMemoryRecordingBackend()
    rabbit = InMemoryRabbit()
    archive = RecordingArchive(enabled=True, minio=minio, rabbit=rabbit)
    stored = archive.archive_completed_call("empty-ch", b"")
    assert stored is not None
    assert stored.size_bytes == 0
    assert len(rabbit.messages) == 1


def test_http_backends_when_loopback_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RVA_RECORDINGS_ENABLE", "1")
    server, port = _start_http_server()
    base = f"http://{_LOOP}:{port}"
    monkeypatch.setenv("RVA_MINIO_ENDPOINT", base)
    monkeypatch.setenv("RVA_RABBITMQ_URL", f"{base}/publish")
    RecordingArchive.reset_shared_for_tests()
    archive = RecordingArchive(enabled=True)
    try:
        pcm = b"\x01" * 64
        stored = archive.archive_completed_call("http-ch", pcm)
        assert stored is not None
        assert any(
            path.endswith(f"/{DEFAULT_FICTIONAL_BUCKET}/calls/http-ch.pcm")
            for path, _ in _RecordingHttpHandler.puts
        )
        assert _RecordingHttpHandler.puts[0][1] == pcm
        assert len(_RecordingHttpHandler.posts) == 1
        msg = json.loads(_RecordingHttpHandler.posts[0])
        assert msg["channel_id"] == "http-ch"
    finally:
        server.shutdown()


def test_http_backend_rejects_public_host() -> None:
    with pytest.raises(RecordingError, match="loopback"):
        HttpMinioBackend("http://example.com:9000")


def test_ari_stasis_end_archives_buffered_pcm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RVA_RECORDINGS_ENABLE", "1")
    RecordingArchive.reset_shared_for_tests()
    CALL_BUFFER.reset_for_tests()
    minio = InMemoryRecordingBackend()
    rabbit = InMemoryRabbit()
    import rva.recordings as recordings_mod

    recordings_mod._ARCHIVE = RecordingArchive(enabled=True, minio=minio, rabbit=rabbit)
    app = AriApp()
    app.handle_event(
        {
            "type": "StasisStart",
            "channel": {"id": "rec-ch"},
            "args": ["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"],
        }
    )
    CALL_BUFFER.append_pcm("rec-ch", b"\x7f\x00" * 100)
    app.handle_event({"type": "StasisEnd", "channel": {"id": "rec-ch"}})
    assert DEFAULT_FICTIONAL_BUCKET in minio.objects
    assert minio.objects[DEFAULT_FICTIONAL_BUCKET]["calls/rec-ch.pcm"] == b"\x7f\x00" * 100


def test_cli_recordings_status_json(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.delenv("RVA_RECORDINGS_ENABLE", raising=False)
    monkeypatch.delenv("RVA_MINIO_ENDPOINT", raising=False)
    monkeypatch.delenv("RVA_RABBITMQ_URL", raising=False)
    RecordingArchive.reset_shared_for_tests()
    code = rva_main(["recordings", "status"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["enabled"] is False
    assert out["bucket"] == DEFAULT_FICTIONAL_BUCKET
    assert out["backends"] == {"minio": "in_memory", "rabbit": "in_memory"}
