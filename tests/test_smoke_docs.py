"""Smoke guide: pjsua/softphone steps in docs only — no Asterisk in CI."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "deploy" / "asterisk" / "SMOKE.md"
ASTERISK_README = ROOT / "deploy" / "asterisk" / "README.md"
EXTENSIONS = ROOT / "deploy" / "asterisk" / "etc" / "extensions.conf"
CI = ROOT / ".github" / "workflows" / "ci.yml"
_AUDIO_UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_STASIS = f"Stasis(rva,{_AUDIO_UUID})"


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
    for needle in ("twilio", "pbx.acme.com", "sip.example.com"):
        assert needle not in text


def test_smoke_doc_matches_dialplan_and_ari_continue_path() -> None:
    smoke = SMOKE.read_text(encoding="utf-8")
    extensions = EXTENSIONS.read_text(encoding="utf-8")
    assert _STASIS in extensions
    assert _STASIS in smoke
    assert "[audiosocket]" in extensions
    assert "[audiosocket]" in smoke
    assert "Answer()" in extensions
    assert "Answer()" in smoke
    assert f"AudioSocket({_AUDIO_UUID},host.docker.internal:8090)" in extensions
    assert "host.docker.internal:8090" in smoke
    assert "StasisStart" in smoke or "continue" in smoke.lower()
    assert "RVA_ARI" in smoke
    assert "direct dialplan" not in smoke.lower()


def test_smoke_md_ends_with_newline() -> None:
    raw = SMOKE.read_bytes()
    assert raw.endswith(b"\n")


def test_asterisk_readme_links_smoke_guide() -> None:
    text = ASTERISK_README.read_text(encoding="utf-8")
    assert "SMOKE.md" in text
    assert "not CI" in text


def test_ci_does_not_run_asterisk_or_pjsua() -> None:
    text = CI.read_text(encoding="utf-8")
    assert "services:" not in text
    for pattern in (
        r"\bdocker\s+compose\b",
        r"\bpjsua\b",
        r"\basterisk\b",
    ):
        assert not re.search(pattern, text, re.IGNORECASE)
