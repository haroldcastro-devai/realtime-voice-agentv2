"""Agent serve prints startup JSON before blocking."""

from __future__ import annotations

import json
from io import StringIO
from unittest.mock import MagicMock, patch

from rva.cli import main


def test_agent_serve_emits_json_before_blocking() -> None:
    runtime = MagicMock()
    runtime.start.return_value = {
        "ari_events": "http://127.0.0.1:8088/ari/events?app=rva",
        "audiosocket_listen": "0.0.0.0:8090",
    }
    runtime.run_until_interrupt.return_value = 0
    buf = StringIO()
    with patch("rva.cli.AgentRuntime", return_value=runtime), patch("rva.cli.sys.stdout", buf):
        code = main(["agent", "serve"])
    assert code == 0
    out = json.loads(buf.getvalue())
    assert out["audiosocket_listen"] == "0.0.0.0:8090"
