"""Optional recordings archive — off by default, fictional bucket, no network."""

from __future__ import annotations

import json

import pytest

from rva.ari import AriApp
from rva.recordings import (
    CALL_BUFFER,
    DEFAULT_FICTIONAL_BUCKET,
    InMemoryRabbit,
    InMemoryRecordingBackend,
    RecordingArchive,
    recordings_enabled,
)


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
