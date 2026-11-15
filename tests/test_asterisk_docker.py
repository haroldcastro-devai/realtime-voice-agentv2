"""Local Asterisk compose + dialplan: loopback SIP, AudioSocket, no cloud PBX.

Does not start Docker or Asterisk (that stays a later smoke-doc issue).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AST = ROOT / "deploy" / "asterisk"
COMPOSE = AST / "docker-compose.yml"
EXTENSIONS = AST / "etc" / "extensions.conf"
PJSIP = AST / "etc" / "pjsip.conf"
DOCS = AST / "README.md"


def test_compose_publishes_sip_on_loopback_only() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    assert "127.0.0.1:5060:5060/udp" in text
    assert "127.0.0.1:5060:5060/tcp" in text
    assert "127.0.0.1:10000-10020:10000-10020/udp" in text
    assert "andrius/asterisk:20" in text
    assert "host.docker.internal:host-gateway" in text
    lowered = text.lower()
    for needle in ("twilio", "sip.example.com", "pbx.acme.com"):
        assert needle not in lowered


def test_extension_1000_audiosocket_to_host_agent() -> None:
    text = EXTENSIONS.read_text(encoding="utf-8")
    assert "exten => 1000," in text
    assert "AudioSocket(" in text
    assert "host.docker.internal:8090" in text
    assert "Answer()" in text


def test_pjsip_demo_endpoint_is_local() -> None:
    text = PJSIP.read_text(encoding="utf-8")
    assert "type=endpoint" in text
    assert "username=ava" in text
    assert "password=rva-demo" in text
    assert "context=from-internal" in text
    assert "bind=0.0.0.0:5060" in text
    assert "external_signaling_address=127.0.0.1" in text


def test_docs_name_extension_and_loopback() -> None:
    text = DOCS.read_text(encoding="utf-8")
    assert "1000" in text
    assert "AudioSocket" in text
    assert "127.0.0.1:5060" in text
    assert "docker compose up" in text
    assert "No cloud PBX" in text
