"""AgentRuntime co-process startup."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from rva.agent import AgentRuntime


def test_start_is_idempotent() -> None:
    client = MagicMock()
    client.register.return_value = "http://127.0.0.1:8088/ari/events?app=rva"
    client.events_url.return_value = "http://127.0.0.1:8088/ari/events?app=rva"
    with (
        patch("rva.agent.AudioSocketServer") as audio_cls,
        patch("rva.agent.threading.Thread") as thread_cls,
    ):
        thread_cls.return_value.start = MagicMock()
        audio_cls.return_value.serve_forever = MagicMock()
        runtime = AgentRuntime(
            client=client,
            app=MagicMock(),
            pipeline=MagicMock(),
            with_dashboard=False,
        )
        first = runtime.start()
        second = runtime.start()
    assert first == second
    client.register.assert_called_once()


def test_stop_shuts_down_ari_socket() -> None:
    import socket

    sock, peer = socket.socketpair()
    runtime = AgentRuntime(client=MagicMock(), app=MagicMock(), pipeline=MagicMock())
    runtime._ari_socket = sock
    runtime.stop()
    assert peer.recv(1) == b""


def test_run_until_interrupt_does_not_restart() -> None:
    runtime = AgentRuntime(client=MagicMock(), app=MagicMock(), pipeline=MagicMock())
    runtime._started = True
    runtime._startup_info = {"ari_events": "u"}
    runtime._stop.set()
    assert runtime.run_until_interrupt() == 0
