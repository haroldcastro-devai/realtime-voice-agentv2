#!/usr/bin/env python3
"""Run N pipeline turns and print per-stage p50/p95 (mock or ``RVA_*_BACKEND`` HTTP).

Uses :func:`rva.pipeline.build_pipeline` without :class:`~rva.colab.ColabOrchestrator`;
HTTP benches exercise OpenAI-compatible URLs directly (Colab worker URL in env), not
in-call fallback/backoff semantics.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from collections.abc import Callable
from typing import Any

from rva import __version__
from rva.metrics import STAGES, StageMetrics
from rva.pipeline import Pipeline, build_pipeline

_BACKEND_KEYS = ("RVA_STT_BACKEND", "RVA_LLM_BACKEND", "RVA_TTS_BACKEND")
_PCM = b"\x00\x00" * 160  # 20 ms @ 16 kHz s16le


def _backend_labels() -> dict[str, str]:
    return {
        key.removeprefix("RVA_").removesuffix("_BACKEND").lower(): _env_backend(key)
        for key in _BACKEND_KEYS
    }


def _env_backend(key: str) -> str:
    raw = os.environ.get(key)
    if raw is None or raw == "" or raw == "CHANGE_ME":
        return "mock"
    return raw


def _platform_info() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "system": platform.system(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
    }


def _dependency_versions() -> dict[str, str]:
    versions: dict[str, str] = {"rva": __version__}
    for name in ("numpy", "scipy"):
        try:
            mod = __import__(name)
        except ImportError:
            continue
        versions[name] = getattr(mod, "__version__", "unknown")
    return versions


def run_benchmark(
    turns: int,
    *,
    factory: Callable[..., Pipeline] = build_pipeline,
) -> dict[str, Any]:
    if turns < 1:
        raise ValueError("turns must be at least 1")
    metrics = StageMetrics(max_samples=max(turns, 16))
    pipe: Pipeline = factory(metrics=metrics)
    for _ in range(turns):
        pipe.turn(_PCM, sample_rate=16_000)
    return {
        "turns": turns,
        "platform": _platform_info(),
        "versions": _dependency_versions(),
        "backends": _backend_labels(),
        "latency_ms": metrics.snapshot(),
    }


def _fmt_ms(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{float(value):.3f}"


def format_report(data: dict[str, Any]) -> str:
    lines = [
        "rva bench-latency",
        f"turns: {data['turns']}",
        (
            "platform: "
            f"{data['platform']['system']} {data['platform']['machine']} "
            f"{data['platform']['processor']} "
            f"py{data['platform']['python']}"
        ),
        ("versions: " + " ".join(f"{key}={val}" for key, val in sorted(data["versions"].items()))),
        ("backends: " + " ".join(f"{key}={val}" for key, val in sorted(data["backends"].items()))),
        "latency_ms:",
    ]
    latency = data["latency_ms"]
    for stage in STAGES:
        row = latency[stage]
        lines.append(
            f"  {stage:5s} n={row['n']} p50={_fmt_ms(row['p50'])} p95={_fmt_ms(row['p95'])}"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bench STT/LLM/TTS/total latency (p50/p95).")
    parser.add_argument(
        "-n",
        "--turns",
        type=int,
        default=32,
        help="Number of pipeline turns (default 32)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON (sorted keys)",
    )
    args = parser.parse_args(argv)
    try:
        data = run_benchmark(args.turns)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        sys.stdout.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(format_report(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
