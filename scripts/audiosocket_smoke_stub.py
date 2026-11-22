#!/usr/bin/env python3
"""Loopback AudioSocket smoke target for deploy/asterisk/SMOKE.md.

Accepts one inbound TCP connection, prints each valid frame, exits on hangup.
Manual use only; pytest covers ``serve_once`` with a local socket, not Asterisk.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import uuid

from rva.audiosocket import Frame, split_frame


def _env_host() -> str:
    raw = os.environ.get("RVA_AUDIOSOCKET_HOST", "0.0.0.0")
    if raw in ("", "CHANGE_ME"):
        return "0.0.0.0"
    return raw


def _env_port() -> int:
    raw = os.environ.get("RVA_AUDIOSOCKET_PORT", "8090")
    try:
        return int(raw)
    except ValueError:
        return 8090


def read_frames_until_hangup(conn: socket.socket, *, read_timeout_s: float = 60.0) -> int:
    """Read AudioSocket frames from an established TCP connection until hangup."""
    conn.settimeout(read_timeout_s)
    buffer = b""
    frames = 0
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            break
        buffer += chunk
        while True:
            frame, buffer = split_frame(buffer)
            if frame is None:
                break
            frames += 1
            _log_frame(frame)
            if frame.is_hangup:
                return frames
    return frames


def serve_once(host: str, port: int, *, accept_timeout_s: float = 60.0) -> int:
    """Listen once, read frames until hangup. Returns number of frames handled."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen(1)
        listener.settimeout(accept_timeout_s)
        conn, _addr = listener.accept()
        with conn:
            return read_frames_until_hangup(conn, read_timeout_s=accept_timeout_s)


def _log_frame(frame: Frame) -> None:
    if frame.is_uuid:
        print(f"audiosocket_smoke: uuid {uuid.UUID(bytes=frame.payload)}", flush=True)
    elif frame.is_hangup:
        print("audiosocket_smoke: hangup", flush=True)
    elif frame.is_pcm:
        print(f"audiosocket_smoke: pcm {len(frame.payload)} bytes", flush=True)
    else:
        print(f"audiosocket_smoke: kind=0x{frame.kind:02x} len={len(frame.payload)}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=_env_host(), help="bind address")
    parser.add_argument("--port", type=int, default=_env_port(), help="bind port")
    parser.add_argument(
        "--accept-timeout",
        type=float,
        default=60.0,
        help="seconds to wait for TCP and read",
    )
    args = parser.parse_args(argv)
    if args.host not in ("0.0.0.0", "127.0.0.1", "::1"):
        print("audiosocket_smoke_stub: bind loopback or 0.0.0.0 only", file=sys.stderr)
        return 2
    count = serve_once(args.host, args.port, accept_timeout_s=args.accept_timeout)
    print(f"audiosocket_smoke: ok ({count} frames)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
