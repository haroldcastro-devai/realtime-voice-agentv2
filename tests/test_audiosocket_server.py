"""AudioSocket TCP server with fake ARI session mapping."""

from __future__ import annotations

import socket
import threading
import time
import uuid

import numpy as np
import pytest
from tests.fakesocket import FakeClock

from rva.ari import AriApp
from rva.audiosocket import HANGUP, PCM, UUID, pack_frame
from rva.audiosocket_server import AudioSocketServer, run_audiosocket_call
from rva.pipeline import build_pipeline
from rva.recordings import CALL_BUFFER

_AUDIO_UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def _stasis_start(channel_id: str) -> dict[str, object]:
    return {
        "type": "StasisStart",
        "channel": {"id": channel_id},
        "args": [_AUDIO_UUID],
    }


def _tone_frame() -> bytes:
    t = np.arange(160, dtype=np.float64) / 8000.0
    wave = 9000 * np.sin(2 * np.pi * 1000.0 * t)
    pcm = np.clip(np.rint(wave), -32768, 32767).astype("<i2").tobytes()
    return pack_frame(PCM, pcm)


def test_run_call_buffers_pcm_and_runs_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RVA_VAD_RMS_THRESHOLD", "100")
    CALL_BUFFER.reset_for_tests()
    app = AriApp()
    app.handle_event(_stasis_start("ch-tcp"))
    session = app.sessions["ch-tcp"]
    pipeline = build_pipeline()
    clock = FakeClock()
    server_sock, client = socket.socketpair()
    for _ in range(6):
        client.sendall(_tone_frame())
    for _ in range(10):
        client.sendall(pack_frame(PCM, b"\x00\x00" * 160))

    done = threading.Event()

    def worker() -> None:
        run_audiosocket_call(
            server_sock,
            ari_app=app,
            pipeline=pipeline,
            channel_id="ch-tcp",
            session=session,
            clock=clock,
        )
        done.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    time.sleep(0.3)
    client.sendall(pack_frame(HANGUP))
    assert done.wait(timeout=3.0)
    client.close()
    pcm = CALL_BUFFER.take_pcm("ch-tcp")
    assert len(pcm) > 0
    stt = pipeline.stt
    assert stt.calls  # type: ignore[attr-defined]
    assert len(clock.sleeps) > 0


def test_server_accepts_uuid_mapped_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RVA_VAD_RMS_THRESHOLD", "100")
    CALL_BUFFER.reset_for_tests()
    app = AriApp()
    app.handle_event(_stasis_start("ch-listen"))
    pipeline = build_pipeline()
    stop = threading.Event()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = AudioSocketServer(app, pipeline, host="127.0.0.1", port=port)
    thread = threading.Thread(target=server.serve_forever, args=(stop,), daemon=True)
    thread.start()
    time.sleep(0.2)
    with socket.create_connection(("127.0.0.1", port), timeout=5.0) as client:
        client.sendall(pack_frame(UUID, uuid.UUID(_AUDIO_UUID).bytes))
        for _ in range(6):
            client.sendall(_tone_frame())
        for _ in range(8):
            client.sendall(pack_frame(PCM, b"\x00\x00" * 160))
        time.sleep(0.5)
        client.sendall(pack_frame(HANGUP))
    stop.set()
    thread.join(timeout=5.0)
    assert pipeline.stt.calls  # type: ignore[attr-defined]
    assert len(CALL_BUFFER.take_pcm("ch-listen")) > 0


def test_run_call_pipeline_turn_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RVA_VAD_RMS_THRESHOLD", "100")
    CALL_BUFFER.reset_for_tests()
    app = AriApp()
    app.handle_event(_stasis_start("ch-two"))
    session = app.sessions["ch-two"]
    pipeline = build_pipeline()
    clock = FakeClock()
    server_sock, client = socket.socketpair()

    def _utterance() -> None:
        for _ in range(6):
            client.sendall(_tone_frame())
        for _ in range(8):
            client.sendall(pack_frame(PCM, b"\x00\x00" * 160))

    done = threading.Event()

    def worker() -> None:
        run_audiosocket_call(
            server_sock,
            ari_app=app,
            pipeline=pipeline,
            channel_id="ch-two",
            session=session,
            clock=clock,
        )
        done.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    stt = pipeline.stt
    _utterance()
    deadline = time.time() + 3.0
    while len(stt.calls) < 1 and time.time() < deadline:  # type: ignore[attr-defined]
        time.sleep(0.05)
    _utterance()
    deadline2 = time.time() + 3.0
    while len(stt.calls) < 2 and time.time() < deadline2:
        time.sleep(0.05)
    client.sendall(pack_frame(HANGUP))
    assert done.wait(timeout=5.0)
    client.close()
    stt = pipeline.stt
    assert len(stt.calls) >= 2  # type: ignore[attr-defined]
