"""ARI WebSocket client against a loopback fake server."""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import threading

from rva.ari import AriClient
from rva.ari_events import _WS_GUID, iter_ari_events, open_ari_events_socket

_LOOP = "127.0.0.1"


def _accept_key(sec_key: str) -> str:
    digest = hashlib.sha1((sec_key + _WS_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def _ws_text_frame(payload: str) -> bytes:
    data = payload.encode("utf-8")
    length = len(data)
    header = bytes([0x81, length])
    return header + data


def test_iter_ari_events_reads_json() -> None:
    event = {"type": "StasisStart", "channel": {"id": "ev-1"}}

    def serve() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((_LOOP, 0))
            sock.listen(1)
            ports["p"] = sock.getsockname()[1]
            ready.set()
            conn, _ = sock.accept()
            with conn:
                request = b""
                while b"\r\n\r\n" not in request:
                    request += conn.recv(4096)
                first_line, rest = request.split(b"\r\n", 1)
                assert b"GET /ari/events" in first_line
                sec_key = None
                for line in rest.split(b"\r\n"):
                    if line.lower().startswith(b"sec-websocket-key:"):
                        sec_key = line.split(b":", 1)[1].strip().decode("ascii")
                        break
                assert sec_key
                accept = _accept_key(sec_key)
                response = (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n"
                    "\r\n"
                ).encode("ascii")
                conn.sendall(response + _ws_text_frame(json.dumps(event)))
                conn.sendall(bytes([0x88, 0x00]))

    ready = threading.Event()
    ports: dict[str, int] = {}
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    assert ready.wait(timeout=2.0)
    assert "p" in ports
    client = AriClient(f"http://{_LOOP}:{ports['p']}", "rva", "rva-ari-demo", app="rva")
    items = list(iter_ari_events(client))
    assert items == [event]
    thread.join(timeout=1.0)


def test_ws_ping_gets_pong() -> None:
    ready = threading.Event()
    port_holder: list[int] = []

    def serve() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((_LOOP, 0))
            sock.listen(1)
            port_holder.append(sock.getsockname()[1])
            ready.set()
            conn, _ = sock.accept()
            with conn:
                request = b""
                while b"\r\n\r\n" not in request:
                    request += conn.recv(4096)
                sec_key = b""
                for line in request.split(b"\r\n"):
                    if line.lower().startswith(b"sec-websocket-key:"):
                        sec_key = line.split(b":", 1)[1].strip()
                accept = _accept_key(sec_key.decode("ascii"))
                conn.sendall(
                    (
                        "HTTP/1.1 101 Switching Protocols\r\n"
                        f"Sec-WebSocket-Accept: {accept}\r\n"
                        "\r\n"
                    ).encode("ascii")
                )
                conn.sendall(bytes([0x89, 0x04]) + b"ping")
                pong_hdr = conn.recv(2)
                assert pong_hdr[0] & 0x0F == 0xA
                payload = conn.recv(4)
                assert payload == b"ping"
                conn.sendall(bytes([0x88, 0x00]))

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    assert ready.wait(timeout=2.0)
    client = AriClient(f"http://{_LOOP}:{port_holder[0]}", "u", "p", app="rva")
    items = list(iter_ari_events(client))
    assert items == []
    thread.join(timeout=1.0)


def test_open_ari_events_socket_upgrade() -> None:
    ready = threading.Event()
    port_holder: list[int] = []

    def serve() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((_LOOP, 0))
            sock.listen(1)
            port_holder.append(sock.getsockname()[1])
            ready.set()
            conn, _ = sock.accept()
            with conn:
                request = b""
                while b"\r\n\r\n" not in request:
                    request += conn.recv(4096)
                sec_key = b"testkey1234567=="
                for line in request.split(b"\r\n"):
                    if line.lower().startswith(b"sec-websocket-key:"):
                        sec_key = line.split(b":", 1)[1].strip()
                accept = _accept_key(sec_key.decode("ascii"))
                conn.sendall(
                    (
                        "HTTP/1.1 101 Switching Protocols\r\n"
                        f"Sec-WebSocket-Accept: {accept}\r\n"
                        "\r\n"
                    ).encode("ascii")
                )
            return

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    assert ready.wait(timeout=2.0)
    client = AriClient(f"http://{_LOOP}:{port_holder[0]}", "u", "p", app="rva")
    conn = open_ari_events_socket(client)
    conn.sock.close()
    thread.join(timeout=1.0)
