"""CLI ``rva agent serve`` startup JSON."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from rva.cli import main


def test_agent_serve_prints_listen_urls() -> None:
    runtime = MagicMock()
    runtime.start.return_value = {
        "ari_events": "http://127.0.0.1:8088/ari/events?app=rva",
        "audiosocket_listen": "0.0.0.0:8090",
        "dashboard_url": "http://127.0.0.1:8765/",
    }
    runtime.run_until_interrupt.return_value = 0
    with patch("rva.cli.AgentRuntime", return_value=runtime):
        code = main(["agent", "serve"])
    assert code == 0
    runtime.start.assert_called_once()
    runtime.run_until_interrupt.assert_called_once()
    runtime.run_until_interrupt.assert_called_with()
