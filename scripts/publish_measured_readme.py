#!/usr/bin/env python3
"""Write ``docs/measured_latency.json`` and sync the README measured-latency section.

``--write`` re-runs :func:`scripts.bench_latency.run_benchmark` on the local machine (mock
backends). Sub-ms mock percentiles can differ across OS/CPU; commit the JSON you intend to ship.
``--check`` (CI) only verifies the README table matches the committed JSON — not cross-platform
numeric parity.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from scripts.bench_latency import run_benchmark

from rva.metrics import STAGES

_REPO = Path(__file__).resolve().parents[1]
_JSON = _REPO / "docs" / "measured_latency.json"
_README = _REPO / "README.md"
_MARKER_START = "<!-- measured-latency-start -->"
_MARKER_END = "<!-- measured-latency-end -->"
_TURNS = 32

_TABLE_HEADER = "| Stage | n | p50 (ms) | p95 (ms) |"
_TABLE_ROW = re.compile(
    r"^\|\s*(?P<stage>\w+)\s*\|\s*(?P<n>\d+)\s*\|\s*(?P<p50>[\d.]+|-)\s*\|\s*(?P<p95>[\d.]+|-)\s*\|$"
)


def _force_mock_backends() -> None:
    for key in ("RVA_STT_BACKEND", "RVA_LLM_BACKEND", "RVA_TTS_BACKEND"):
        os.environ[key] = "mock"


def _fmt_ms(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{float(value):.3f}"


def render_measured_section(data: dict[str, object]) -> str:
    lat = data["latency_ms"]
    assert isinstance(lat, dict)
    lines = [
        _MARKER_START,
        "",
        "## Measured latency (mock)",
        "",
        "Source: [`docs/measured_latency.json`](docs/measured_latency.json) "
        f"({data['turns']} turns, mock backends). "
        "Platform, processor, and dependency versions live in that JSON only — not in the table "
        "below. "
        "Regenerate after re-benchmarking (percentiles may differ by machine; CI checks "
        "README↔JSON sync via ``--check``):",
        "",
        "```bash",
        "python scripts/publish_measured_readme.py --write",
        "```",
        "",
        "| Stage | n | p50 (ms) | p95 (ms) |",
        "| --- | ---: | ---: | ---: |",
    ]
    for stage in STAGES:
        row = lat[stage]
        assert isinstance(row, dict)
        lines.append(f"| {stage} | {row['n']} | {_fmt_ms(row['p50'])} | {_fmt_ms(row['p95'])} |")
    lines.extend(
        [
            "",
            "Short portfolio demo narration: "
            "[docs/DEMO_VIDEO_SCRIPT.md](docs/DEMO_VIDEO_SCRIPT.md).",
            "",
            _MARKER_END,
        ]
    )
    return "\n".join(lines) + "\n"


def replace_marked_block(readme_text: str, section: str) -> str:
    pattern = re.compile(
        re.escape(_MARKER_START) + r".*?" + re.escape(_MARKER_END) + r"\n?",
        re.DOTALL,
    )
    if not pattern.search(readme_text):
        raise ValueError("README missing measured-latency markers")
    return pattern.sub(section.rstrip() + "\n", readme_text, count=1)


def parse_table_from_readme(readme_text: str) -> dict[str, dict[str, float | int | None]]:
    start = readme_text.find(_MARKER_START)
    end = readme_text.find(_MARKER_END)
    if start < 0 or end < 0:
        raise ValueError("README missing measured-latency markers")
    block = readme_text[start:end]
    if _TABLE_HEADER not in block:
        raise ValueError("README measured table header missing")
    parsed: dict[str, dict[str, float | int | None]] = {}
    for line in block.splitlines():
        match = _TABLE_ROW.match(line.strip())
        if not match:
            continue
        stage = match.group("stage")
        p50_raw = match.group("p50")
        p95_raw = match.group("p95")
        parsed[stage] = {
            "n": int(match.group("n")),
            "p50": None if p50_raw == "-" else float(p50_raw),
            "p95": None if p95_raw == "-" else float(p95_raw),
        }
    if set(parsed) != set(STAGES):
        raise ValueError("README measured table stages mismatch")
    return parsed


def load_json() -> dict[str, object]:
    return json.loads(_JSON.read_text(encoding="utf-8"))


def latency_matches(a: dict[str, object], b: dict[str, object]) -> bool:
    lat_a = a.get("latency_ms")
    lat_b = b.get("latency_ms")
    if not isinstance(lat_a, dict) or not isinstance(lat_b, dict):
        return False
    for stage in STAGES:
        row_a = lat_a.get(stage)
        row_b = lat_b.get(stage)
        if not isinstance(row_a, dict) or not isinstance(row_b, dict):
            return False
        if row_a.get("n") != row_b.get("n"):
            return False
        for key in ("p50", "p95"):
            if _fmt_ms(row_a.get(key)) != _fmt_ms(row_b.get(key)):
                return False
    return True


def write_artifacts(data: dict[str, object]) -> None:
    _JSON.parent.mkdir(parents=True, exist_ok=True)
    _JSON.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    section = render_measured_section(data)
    readme = _README.read_text(encoding="utf-8")
    _README.write_text(replace_marked_block(readme, section), encoding="utf-8")


def check_artifacts() -> bool:
    data = load_json()
    readme = _README.read_text(encoding="utf-8")
    table = parse_table_from_readme(readme)
    lat = data["latency_ms"]
    assert isinstance(lat, dict)
    for stage in STAGES:
        row = lat[stage]
        assert isinstance(row, dict)
        if row.get("n") != table[stage]["n"]:
            return False
        if _fmt_ms(row.get("p50")) != _fmt_ms(table[stage]["p50"]):
            return False
        if _fmt_ms(row.get("p95")) != _fmt_ms(table[stage]["p95"]):
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync measured mock latency into README.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="Run bench and update JSON + README")
    group.add_argument("--check", action="store_true", help="Verify README matches JSON (CI)")
    args = parser.parse_args(argv)
    if args.write:
        _force_mock_backends()
        data = run_benchmark(_TURNS)
        write_artifacts(data)
        return 0
    if not check_artifacts():
        print("README measured table does not match docs/measured_latency.json", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
