"""Smoke guide: pjsua/softphone steps in docs only — no Asterisk in CI."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "deploy" / "asterisk" / "SMOKE.md"
ASTERISK_README = ROOT / "deploy" / "asterisk" / "README.md"
CI = ROOT / ".github" / "workflows" / "ci.yml"


def test_smoke_doc_covers_pjsua_softphone_and_extension_1000() -> None:
    text = SMOKE.read_text(encoding="utf-8")
    assert "not CI" in text or "not in CI" in text
    assert "pjsua" in text
    assert "softphone" in text.lower()
    assert "1000" in text
    assert "127.0.0.1:5060" in text
    assert "ava" in text
    assert "rva-demo" in text
    assert "0.0.0.0:8090" in text or "8090" in text
    assert "audiosocket_smoke_stub.py" in text
    assert "docker compose up" in text
    for needle in ("twilio", "8.8.8.8", "sip.example.com"):
        assert needle not in text


def test_asterisk_readme_links_smoke_guide() -> None:
    text = ASTERISK_README.read_text(encoding="utf-8")
    assert "SMOKE.md" in text
    assert "not CI" in text


def test_ci_does_not_run_asterisk_or_pjsua() -> None:
    text = CI.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "docker compose" not in lowered
    assert "pjsua" not in lowered
    assert "asterisk" not in lowered
