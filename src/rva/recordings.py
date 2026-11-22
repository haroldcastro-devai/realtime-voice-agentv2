"""Optional post-call PCM archive (fictional MinIO bucket + RabbitMQ notice).

Disabled unless ``RVA_RECORDINGS_ENABLE=1``. Default bucket name is fictional;
no real subscriber audio is required for pytest.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass

DEFAULT_FICTIONAL_BUCKET = "acme-ava-recordings-fictional"
_ENV_ENABLE = "RVA_RECORDINGS_ENABLE"
_ENV_BUCKET = "RVA_MINIO_BUCKET"
_ENV_MINIO = "RVA_MINIO_ENDPOINT"
_ENV_RABBIT = "RVA_RABBITMQ_URL"


class RecordingError(ValueError):
    """Invalid configuration or payload."""


def _env_flag(name: str) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "" or raw == "CHANGE_ME":
        return False
    return raw.strip().lower() in ("1", "true", "yes", "on")


def recordings_enabled() -> bool:
    return _env_flag(_ENV_ENABLE)


def minio_bucket_name() -> str:
    raw = os.environ.get(_ENV_BUCKET)
    if raw is None or raw == "" or raw == "CHANGE_ME":
        return DEFAULT_FICTIONAL_BUCKET
    return raw


@dataclass(frozen=True, slots=True)
class StoredObject:
    bucket: str
    key: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class RecordingNotice:
    channel_id: str
    bucket: str
    key: str
    size_bytes: int


class CallRecordingBuffer:
    """Per-channel mono PCM accumulator (in-process until StasisEnd)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._channels: dict[str, bytearray] = {}

    def append_pcm(self, channel_id: str, pcm: bytes) -> None:
        if not channel_id:
            raise RecordingError("channel_id required")
        with self._lock:
            buf = self._channels.setdefault(channel_id, bytearray())
            buf.extend(pcm)

    def take_pcm(self, channel_id: str) -> bytes:
        with self._lock:
            data = bytes(self._channels.pop(channel_id, b""))
        return data

    def reset_for_tests(self) -> None:
        with self._lock:
            self._channels.clear()


CALL_BUFFER = CallRecordingBuffer()


class InMemoryRecordingBackend:
    """Test/double MinIO: bucket -> key -> bytes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.objects: dict[str, dict[str, bytes]] = {}

    def put_object(self, bucket: str, key: str, body: bytes) -> StoredObject:
        with self._lock:
            store = self.objects.setdefault(bucket, {})
            store[key] = bytes(body)
        return StoredObject(bucket=bucket, key=key, size_bytes=len(body))

    def reset_for_tests(self) -> None:
        with self._lock:
            self.objects.clear()


class InMemoryRabbit:
    """Test/double queue: append-only notices."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.messages: list[str] = []

    def publish(self, payload: dict[str, object]) -> None:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        with self._lock:
            self.messages.append(body)

    def reset_for_tests(self) -> None:
        with self._lock:
            self.messages.clear()


class RecordingArchive:
    """Archive completed call audio and emit a fictional completion notice."""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        bucket: str | None = None,
        minio: InMemoryRecordingBackend | None = None,
        rabbit: InMemoryRabbit | None = None,
    ) -> None:
        self._enabled = recordings_enabled() if enabled is None else enabled
        self._bucket = minio_bucket_name() if bucket is None else bucket
        self._minio = minio if minio is not None else InMemoryRecordingBackend()
        self._rabbit = rabbit if rabbit is not None else InMemoryRabbit()

    @classmethod
    def shared(cls) -> RecordingArchive:
        global _ARCHIVE
        if _ARCHIVE is None:
            _ARCHIVE = cls()
        return _ARCHIVE

    @classmethod
    def reset_shared_for_tests(cls) -> None:
        global _ARCHIVE
        _ARCHIVE = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def archive_completed_call(self, channel_id: str, pcm: bytes) -> StoredObject | None:
        if not self._enabled:
            return None
        if not channel_id:
            raise RecordingError("channel_id required")
        key = f"calls/{channel_id}.pcm"
        stored = self._minio.put_object(self._bucket, key, pcm)
        notice: RecordingNotice = RecordingNotice(
            channel_id=channel_id,
            bucket=stored.bucket,
            key=stored.key,
            size_bytes=stored.size_bytes,
        )
        self._rabbit.publish(
            {
                "event": "call_recording_archived",
                "channel_id": notice.channel_id,
                "bucket": notice.bucket,
                "key": notice.key,
                "size_bytes": notice.size_bytes,
            }
        )
        return stored


_ARCHIVE: RecordingArchive | None = None
