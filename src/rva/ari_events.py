"""ARI application event stream over WebSocket (stdlib only)."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
from collections.abc import Iterator
from json import JSONDecodeError
from urllib.parse import urlparse

from rva.ari import AriClient, AriError

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


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


def _ws_handshake(sock: socket.socket, host: str, path: str, auth_header: str) -> None:
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
    header, _body = response.split(b"\r\n\r\n", 1)
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


def _read_ws_text(sock: socket.socket) -> str | None:
    hdr = _read_exact(sock, 2)
    opcode = hdr[0] & 0x0F
    masked = bool(hdr[1] & 0x80)
    length = hdr[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", _read_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _read_exact(sock, 8))[0]
    mask_key = b""
    if masked:
        mask_key = _read_exact(sock, 4)
    payload = _read_exact(sock, length)
    if masked:
        payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    if opcode == 0x8:
        return None
    if opcode != 0x1:
        return ""
    return payload.decode("utf-8")


def open_ari_events_socket(client: AriClient) -> socket.socket:
    """TCP socket after a successful ARI events WebSocket handshake."""
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
    _ws_handshake(sock, f"{host}:{port}", path, f"Basic {token}")
    sock.settimeout(_timeout())
    return sock


def iter_ari_events(client: AriClient) -> Iterator[dict[str, object]]:
    """Yield ARI JSON event objects until the WebSocket closes."""
    sock = open_ari_events_socket(client)
    try:
        while True:
            try:
                raw = _read_ws_text(sock)
            except (TimeoutError, OSError) as exc:
                raise AriError(str(exc)) from exc
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
        sock.close()
