"""Public Asterisk AudioSocket frame codec (header + payload only).

On the wire each frame is three header bytes then a payload:

* kind (uint8)
* payload length (uint16, big-endian)
* payload (0..65535 bytes)

Kinds used by this parser: hangup ``0x00``, UUID ``0x01``, 8 kHz 16-bit LE PCM
``0x10``, error ``0xff``. Call-session and TCP serving are out of scope here.
"""

from __future__ import annotations

from dataclasses import dataclass

HANGUP = 0x00
UUID = 0x01
PCM = 0x10
ERROR = 0xFF

_KNOWN_KINDS = frozenset({HANGUP, UUID, PCM, ERROR})
_HEADER_LEN = 3
_UUID_LEN = 16
_MAX_PAYLOAD = 65_535


class FrameError(ValueError):
    """The buffer is a complete but illegal AudioSocket frame."""


@dataclass(frozen=True, slots=True)
class Frame:
    kind: int
    payload: bytes

    @property
    def is_hangup(self) -> bool:
        return self.kind == HANGUP

    @property
    def is_uuid(self) -> bool:
        return self.kind == UUID

    @property
    def is_pcm(self) -> bool:
        return self.kind == PCM


def pack_frame(kind: int, payload: bytes = b"") -> bytes:
    """Serialize one frame. Raises FrameError if the kind/payload pair is illegal."""
    _validate(kind, payload)
    length = len(payload)
    return bytes((kind, (length >> 8) & 0xFF, length & 0xFF)) + payload


def parse_frame(data: bytes) -> Frame:
    """Parse exactly one complete frame. Extra or missing bytes are errors."""
    if len(data) < _HEADER_LEN:
        raise FrameError("truncated header")
    kind = data[0]
    length = (data[1] << 8) | data[2]
    needed = _HEADER_LEN + length
    if len(data) < needed:
        raise FrameError("truncated payload")
    if len(data) > needed:
        raise FrameError("trailing bytes after frame")
    payload = data[_HEADER_LEN:needed]
    _validate(kind, payload)
    return Frame(kind=kind, payload=payload)


def split_frame(buffer: bytes) -> tuple[Frame | None, bytes]:
    """If ``buffer`` starts with a complete valid frame, return it and the rest.

    Incomplete input returns ``(None, buffer)``. A complete illegal frame raises
    ``FrameError`` (the remainder is not consumed).
    """
    if len(buffer) < _HEADER_LEN:
        return None, buffer
    length = (buffer[1] << 8) | buffer[2]
    needed = _HEADER_LEN + length
    if len(buffer) < needed:
        return None, buffer
    frame = parse_frame(buffer[:needed])
    return frame, buffer[needed:]


def _validate(kind: int, payload: bytes) -> None:
    if kind not in _KNOWN_KINDS:
        raise FrameError(f"unknown kind 0x{kind:02x}")
    if len(payload) > _MAX_PAYLOAD:
        raise FrameError("payload exceeds 65535 bytes")
    if kind == UUID and len(payload) != _UUID_LEN:
        raise FrameError("uuid payload must be 16 bytes")
    if kind == HANGUP and payload:
        raise FrameError("hangup payload must be empty")
    if kind == PCM and (not payload or len(payload) % 2):
        raise FrameError("pcm payload must be non-empty little-endian s16 pairs")
