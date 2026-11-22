"""Unit test for the manual AudioSocket smoke stub (loopback TCP only)."""

from __future__ import annotations

import socket
import threading
import time
import uuid

from scripts.audiosocket_smoke_stub import read_frames_until_hangup, serve_once

from rva.audiosocket import HANGUP, UUID, pack_frame

_LOOP = "127.0.0.1"
_AUDIO_UUID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def test_read_frames_until_hangup_on_socketpair() -> None:
    server, client = socket.socketpair()
    with server, client:
        client.sendall(pack_frame(UUID, _AUDIO_UUID.bytes))
        client.sendall(pack_frame(HANGUP))
        count = read_frames_until_hangup(server, read_timeout_s=2.0)
    assert count == 2


def test_serve_once_reads_uuid_then_hangup() -> None:
    bind = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    bind.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    bind.bind((_LOOP, 0))
    port = bind.getsockname()[1]
    bind.close()
    count_box: list[int] = []

    def run_server() -> None:
        count_box.append(serve_once(_LOOP, port, accept_timeout_s=5.0))

    def run_client() -> None:
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            try:
                with socket.create_connection((_LOOP, port), timeout=0.25) as sock:
                    sock.sendall(pack_frame(UUID, _AUDIO_UUID.bytes))
                    sock.sendall(pack_frame(HANGUP))
                    return
            except OSError:
                time.sleep(0.05)

    server = threading.Thread(target=run_server, daemon=True)
    client = threading.Thread(target=run_client, daemon=True)
    server.start()
    client.start()
    server.join(timeout=6.0)
    client.join(timeout=6.0)
    assert count_box == [2]
