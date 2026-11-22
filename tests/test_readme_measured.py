"""README latency table must match committed measured JSON (no invented numbers)."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.publish_measured_readme import (
    _fmt_ms,
    check_artifacts,
    main,
    parse_table_from_readme,
)

from rva.metrics import STAGES

_REPO = Path(__file__).resolve().parents[1]
_JSON = _REPO / "docs" / "measured_latency.json"
_README = _REPO / "README.md"


def test_measured_json_has_expected_shape() -> None:
    data = json.loads(_JSON.read_text(encoding="utf-8"))
    assert data["turns"] == 32
    assert data["backends"] == {"llm": "mock", "stt": "mock", "tts": "mock"}
    for stage in STAGES:
        row = data["latency_ms"][stage]
        assert row["n"] == 32
        assert isinstance(row["p50"], (int, float))
        assert isinstance(row["p95"], (int, float))


def test_readme_table_matches_measured_json() -> None:
    assert check_artifacts() is True
    table = parse_table_from_readme(_README.read_text(encoding="utf-8"))
    data = json.loads(_JSON.read_text(encoding="utf-8"))
    lat = data["latency_ms"]
    for stage in STAGES:
        assert table[stage]["n"] == lat[stage]["n"]
        assert _fmt_ms(table[stage]["p50"]) == _fmt_ms(lat[stage]["p50"])
        assert _fmt_ms(table[stage]["p95"]) == _fmt_ms(lat[stage]["p95"])


def test_publish_check_cli_exits_zero() -> None:
    assert main(["--check"]) == 0


def test_parse_table_requires_header() -> None:
    import pytest
    from scripts.publish_measured_readme import _MARKER_END, _MARKER_START

    bad = f"{_MARKER_START}\n| stt | 1 | 0 | 0 |\n{_MARKER_END}"
    with pytest.raises(ValueError, match="header"):
        parse_table_from_readme(bad)


def test_demo_video_script_has_expected_beats() -> None:
    text = (_REPO / "docs" / "DEMO_VIDEO_SCRIPT.md").read_text(encoding="utf-8")
    assert len(text.strip()) > 100
    for token in ("Ava", "bench_latency", "dashboard", "Acme"):
        assert token in text
