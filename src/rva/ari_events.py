"""ARI application event stream over WebSocket (stdlib only)."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
from collections.abc import Iterator
from dataclasses import dataclass, field
from json import JSONDecodeError
from urllib.parse import urlparse

from rva.ari import AriClient, AriError

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


@dataclass
class AriWsConnection:
    """One ARI events WebSocket with optional post-handshake bytes buffered."""

    sock: socket.socket
    pending: bytes = field(default=b"")


def _timeout() -> float:
    raw = os.environ.get("RVA_HTTP_TIMEOUT")
    if raw is None or raw in ("", "CHANGE_ME"):
        return 30.0
    try:
        value = float(raw)
    except ValueError:
        return 30.0
    return max(value, 5.0)


def _read_exact(sock: socket.socket, nbytes: int) -> bytes:
    chunks: list[bytes] = []
    remaining = nbytes
    while remaining > 0:
        block = sock.recv(remaining)
        if not block:
            raise AriError("ARI WebSocket closed while reading")
        chunks.append(block)
        remaining -= len(block)
    return b"".join(chunks)


def _ws_handshake(sock: socket.socket, host: str, path: str, auth_header: str) -> bytes:
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        f"Authorization: {auth_header}\r\n"
        "\r\n"
    ).encode("ascii")
    sock.sendall(request)
    response = b""
    while b"\r\n\r\n" not in response:
        chunk = sock.recv(4096)
        if not chunk:
            raise AriError("ARI WebSocket handshake failed")
        response += chunk
    header, body = response.split(b"\r\n\r\n", 1)
    if b"101" not in header.split(b"\r\n", 1)[0]:
        raise AriError("ARI WebSocket upgrade rejected")
    accept = None
    for line in header.split(b"\r\n"):
        if line.lower().startswith(b"sec-websocket-accept:"):
            accept = line.split(b":", 1)[1].strip().decode("ascii")
            break
    digest = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()).decode(
        "ascii"
    )
    if accept != digest:
        raise AriError("ARI WebSocket accept mismatch")
    return body


def _take(conn: AriWsConnection, nbytes: int) -> bytes:
    if len(conn.pending) >= nbytes:
        out = conn.pending[:nbytes]
        conn.pending = conn.pending[nbytes:]
        return out
    need = nbytes - len(conn.pending)
    out = conn.pending + _read_exact(conn.sock, need)
    conn.pending = b""
    return out


def _send_ws_pong(sock: socket.socket, payload: bytes) -> None:
    length = len(payload)
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    if length < 126:
        header = bytes([0x8A, 0x80 | length])
    elif length < 65536:
        header = bytes([0x8A, 0x80 | 126]) + struct.pack("!H", length)
    else:
        header = bytes([0x8A, 0x80 | 127]) + struct.pack("!Q", length)
    sock.sendall(header + mask + masked)


def _read_ws_message(conn: AriWsConnection) -> tuple[int, bytes | None, bool]:
    """Read one WebSocket frame; returns ``(opcode, payload, fin)`` or ``(0x8, None, True)``."""
    while True:
        hdr = _take(conn, 2)
        fin = bool(hdr[0] & 0x80)
        opcode = hdr[0] & 0x0F
        masked = bool(hdr[1] & 0x80)
        length = hdr[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", _take(conn, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", _take(conn, 8))[0]
        mask_key = _take(conn, 4) if masked else b""
        payload = _take(conn, length)
        if masked:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        if opcode == 0x8:
            return 0x8, None, True
        if opcode == 0x9:
            _send_ws_pong(conn.sock, payload)
            continue
        if opcode == 0xA:
            continue
        return opcode, payload, fin


def _read_ws_text(conn: AriWsConnection) -> str | None:
    parts: list[bytes] = []
    while True:
        opcode, payload, fin = _read_ws_message(conn)
        if opcode == 0x8 or payload is None:
            return None
        if opcode in (0x0, 0x1):
            parts.append(payload)
            if fin:
                return b"".join(parts).decode("utf-8")
            continue
        parts.clear()


def open_ari_events_socket(client: AriClient) -> AriWsConnection:
    """WebSocket to ARI events with handshake bytes retained for the first frame."""
    url = client.events_url()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise AriError("ARI events URL must be http(s)")
    host = parsed.hostname
    if host is None:
        raise AriError("ARI events URL missing host")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if parsed.scheme == "https":
        raise AriError("ARI WebSocket over TLS is not implemented (use http loopback)")
    sock = socket.create_connection((host, port), timeout=_timeout())
    token = base64.b64encode(f"{client.user}:{client.password}".encode()).decode("ascii")
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    pending = _ws_handshake(sock, f"{host}:{port}", path, f"Basic {token}")
    sock.settimeout(None)
    return AriWsConnection(sock=sock, pending=pending)


def iter_ari_events(client: AriClient) -> Iterator[dict[str, object]]:
    """Yield ARI JSON event objects until the WebSocket closes."""
    conn = open_ari_events_socket(client)
    try:
        while True:
            raw = _read_ws_text(conn)
            if raw is None:
                break
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except JSONDecodeError as exc:
                raise AriError("ARI event is not JSON") from exc
            if isinstance(data, dict):
                yield data
    finally:
        conn.sock.close()
