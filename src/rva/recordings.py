"""Optional post-call PCM archive (fictional MinIO bucket + RabbitMQ notice).

Disabled unless ``RVA_RECORDINGS_ENABLE=1``. Default bucket name is fictional.
``CALL_BUFFER.append_pcm`` is for tests and future AudioSocket wiring (not hooked yet).

When ``RVA_MINIO_ENDPOINT`` / ``RVA_RABBITMQ_URL`` are unset or ``CHANGE_ME``, in-memory
doubles are used. Loopback HTTP PUT/POST is used when those URLs point at ``127.0.0.1`` /
``localhost`` / ``::1``. An empty PCM payload still produces an object and notice when enabled.

``RecordingArchive.shared()`` builds from environment once; tests inject via ``_ARCHIVE`` or
pass explicit ``minio`` / ``rabbit`` to :class:`RecordingArchive`.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_FICTIONAL_BUCKET = "acme-ava-recordings-fictional"
_ENV_ENABLE = "RVA_RECORDINGS_ENABLE"
_ENV_BUCKET = "RVA_MINIO_BUCKET"
_ENV_MINIO = "RVA_MINIO_ENDPOINT"
_ENV_RABBIT = "RVA_RABBITMQ_URL"
_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})


class RecordingError(ValueError):
    """Invalid configuration or payload."""


class ObjectStore(Protocol):
    def put_object(self, bucket: str, key: str, body: bytes) -> StoredObject: ...


class NoticePublisher(Protocol):
    def publish(self, payload: dict[str, object]) -> None: ...


def _env_flag(name: str) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "" or raw == "CHANGE_ME":
        return False
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _configured_url(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "" or raw == "CHANGE_ME":
        return None
    return raw.strip().rstrip("/")


def _require_loopback(url: str) -> None:
    host = urlparse(url).hostname
    if host not in _LOOPBACK:
        raise RecordingError("recording HTTP endpoints must be loopback")


def recordings_enabled() -> bool:
    return _env_flag(_ENV_ENABLE)


def minio_bucket_name() -> str:
    raw = os.environ.get(_ENV_BUCKET)
    if raw is None or raw == "" or raw == "CHANGE_ME":
        return DEFAULT_FICTIONAL_BUCKET
    return raw


def recording_backend_modes() -> dict[str, str]:
    minio_url = _configured_url(_ENV_MINIO)
    rabbit_url = _configured_url(_ENV_RABBIT)
    return {
        "minio": "http" if minio_url else "in_memory",
        "rabbit": "http" if rabbit_url else "in_memory",
    }


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
    """In-process MinIO double: bucket -> key -> bytes."""

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


class HttpMinioBackend:
    """Loopback HTTP PUT ``{endpoint}/{bucket}/{key}``."""

    def __init__(self, endpoint: str) -> None:
        _require_loopback(endpoint)
        self._endpoint = endpoint.rstrip("/")

    def put_object(self, bucket: str, key: str, body: bytes) -> StoredObject:
        path = f"/{bucket}/{key}"
        url = f"{self._endpoint}{path}"
        request = Request(url, data=body, method="PUT")
        try:
            with urlopen(request, timeout=10) as response:
                response.read()
        except (HTTPError, URLError) as exc:
            raise RecordingError(f"minio put failed: {exc}") from exc
        return StoredObject(bucket=bucket, key=key, size_bytes=len(body))


class InMemoryRabbit:
    """In-process RabbitMQ double: append-only notices."""

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


class HttpRabbitPublisher:
    """Loopback HTTP POST JSON to ``RVA_RABBITMQ_URL``."""

    def __init__(self, url: str) -> None:
        _require_loopback(url)
        self._url = url

    def publish(self, payload: dict[str, object]) -> None:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        request = Request(
            self._url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urlopen(request, timeout=10) as response:
                response.read()
        except (HTTPError, URLError) as exc:
            raise RecordingError(f"rabbit publish failed: {exc}") from exc


def _build_object_store(explicit: ObjectStore | None) -> ObjectStore:
    if explicit is not None:
        return explicit
    url = _configured_url(_ENV_MINIO)
    if url:
        return HttpMinioBackend(url)
    return InMemoryRecordingBackend()


def _build_publisher(explicit: NoticePublisher | None) -> NoticePublisher:
    if explicit is not None:
        return explicit
    url = _configured_url(_ENV_RABBIT)
    if url:
        return HttpRabbitPublisher(url)
    return InMemoryRabbit()


class RecordingArchive:
    """Archive completed call audio and emit a completion notice."""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        bucket: str | None = None,
        minio: ObjectStore | None = None,
        rabbit: NoticePublisher | None = None,
    ) -> None:
        self._enabled = recordings_enabled() if enabled is None else enabled
        self._bucket = minio_bucket_name() if bucket is None else bucket
        self._minio = _build_object_store(minio)
        self._rabbit = _build_publisher(rabbit)

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
        """Store ``pcm`` (may be empty) and publish a notice when enabled."""
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
