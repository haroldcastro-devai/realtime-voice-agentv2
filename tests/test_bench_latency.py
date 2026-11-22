"""bench_latency.py — mocked turns, stable JSON, no accidental network in CI."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.bench_latency import format_report, main, run_benchmark

from rva.metrics import STAGES

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "bench_latency.py"
_MOCK_BACKEND_KEYS = ("RVA_STT_BACKEND", "RVA_LLM_BACKEND", "RVA_TTS_BACKEND")


def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _block(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("bench must not use the network with mock backends")

    monkeypatch.setattr(socket, "create_connection", _block)
    monkeypatch.setattr(socket.socket, "connect", _block)


def _mock_bench_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(_REPO / "src"), str(_REPO)])
    for key in _MOCK_BACKEND_KEYS:
        env[key] = "mock"
    return env


def _run_cli_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        cwd=_REPO,
        env=_mock_bench_env(),
        capture_output=True,
        text=True,
        check=False,
    )


def test_run_benchmark_mock_backends_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _MOCK_BACKEND_KEYS:
        monkeypatch.delenv(key, raising=False)
    _block_network(monkeypatch)
    data = run_benchmark(8)
    assert data["turns"] == 8
    assert data["backends"] == {"stt": "mock", "llm": "mock", "tts": "mock"}
    for stage in STAGES:
        row = data["latency_ms"][stage]
        assert row["n"] == 8
        assert row["p50"] is not None
        assert row["p95"] is not None


def test_format_report_is_stable_text() -> None:
    sample = {
        "turns": 2,
        "platform": {
            "python": "3.12.0",
            "system": "Linux",
            "machine": "x86_64",
            "processor": "x",
        },
        "versions": {"rva": "0.2.0"},
        "backends": {"llm": "mock", "stt": "mock", "tts": "mock"},
        "latency_ms": {name: {"n": 2, "p50": 1.0, "p95": 2.0} for name in STAGES},
    }
    text = format_report(sample)
    assert "rva bench-latency" in text
    assert "p50=1.000" in text
    assert "stt" in text
    assert " x py3.12.0" in text


def test_main_rejects_invalid_turns() -> None:
    assert main(["-n", "0"]) == 2


def test_cli_json_stdout() -> None:
    proc = _run_cli_script("-n", "4", "--json")
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["turns"] == 4
    assert data["latency_ms"]["total"]["n"] == 4
    assert data["backends"] == {"llm": "mock", "stt": "mock", "tts": "mock"}


def test_cli_text_stdout() -> None:
    proc = _run_cli_script("-n", "4")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("rva bench-latency\n")
    assert "latency_ms:" in proc.stdout
    assert "total" in proc.stdout
