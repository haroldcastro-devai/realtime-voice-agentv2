"""Local Asterisk compose + dialplan: loopback SIP, AudioSocket, no cloud PBX.

Does not start Docker or Asterisk. Manual smoke steps live in deploy/asterisk/SMOKE.md.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AST = ROOT / "deploy" / "asterisk"
COMPOSE = AST / "docker-compose.yml"
EXTENSIONS = AST / "etc" / "extensions.conf"
PJSIP = AST / "etc" / "pjsip.conf"
MODULES = AST / "etc" / "modules.conf"
DOCS = AST / "README.md"
ENV_EXAMPLE = ROOT / ".env.example"

_IMAGE_DIGEST = "sha256:75d8c7b2f01d24c8d8d97c23621ecee5a031f6d6c79f635258dd4293c8d46d89"
_AUDIO_UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def test_compose_publishes_sip_on_loopback_only() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    assert "127.0.0.1:5060:5060/udp" in text
    assert "127.0.0.1:5060:5060/tcp" not in text
    assert "127.0.0.1:8088:8088" in text
    assert "127.0.0.1:10000-10020:10000-10020/udp" in text
    assert f"andrius/asterisk:20@{_IMAGE_DIGEST}" in text
    assert "host.docker.internal:host-gateway" in text
    lowered = text.lower()
    for needle in ("twilio", "sip.example.com", "pbx.acme.com"):
        assert needle not in lowered


def test_extension_1000_stasis_then_audiosocket() -> None:
    text = EXTENSIONS.read_text(encoding="utf-8")
    assert "exten => 1000," in text
    assert f"Stasis(rva,{_AUDIO_UUID})" in text
    assert "[audiosocket]" in text
    assert f"AudioSocket({_AUDIO_UUID},host.docker.internal:8090)" in text
    assert "Answer()" in text


def test_agent_bind_pairs_with_host_gateway() -> None:
    env = ENV_EXAMPLE.read_text(encoding="utf-8")
    docs = DOCS.read_text(encoding="utf-8")
    assert "RVA_AUDIOSOCKET_HOST=0.0.0.0" in env
    assert "RVA_AUDIOSOCKET_PORT=8090" in env
    assert "0.0.0.0:8090" in docs
    assert "host.docker.internal:8090" in docs
    assert "127.0.0.1:5060" in docs


def test_pjsip_demo_endpoint_is_local() -> None:
    text = PJSIP.read_text(encoding="utf-8")
    assert "type=endpoint" in text
    assert "transport=transport-udp" in text
    assert "username=ava" in text
    assert "password=rva-demo" in text
    assert "context=from-internal" in text
    assert "bind=0.0.0.0:5060" in text
    assert "external_signaling_address=127.0.0.1" in text
    assert "protocol=tcp" not in text


def test_modules_load_pjsip_and_audiosocket() -> None:
    text = MODULES.read_text(encoding="utf-8")
    assert "noload => chan_sip.so" in text
    for name in (
        "res_pjsip.so",
        "res_pjsip_session.so",
        "chan_pjsip.so",
        "res_audiosocket.so",
        "app_audiosocket.so",
        "res_stasis.so",
        "app_stasis.so",
        "res_http_websocket.so",
        "res_ari.so",
        "res_ari_model.so",
        "res_ari_events.so",
        "res_ari_channels.so",
        "res_ari_asterisk.so",
    ):
        assert f"load => {name}" in text


def test_ari_http_enabled_on_loopback_publish() -> None:
    http = (AST / "etc" / "http.conf").read_text(encoding="utf-8")
    ari = (AST / "etc" / "ari.conf").read_text(encoding="utf-8")
    env = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "enabled=yes" in http
    assert "bindport=8088" in http
    assert "bindaddr=0.0.0.0" in http
    assert "[rva]" in ari
    assert "password=rva-ari-demo" in ari
    assert "RVA_ARI_URL=http://127.0.0.1:8088" in env
    assert "RVA_ARI_APP=rva" in env


def test_docs_name_extension_and_loopback() -> None:
    text = DOCS.read_text(encoding="utf-8")
    assert "1000" in text
    assert "AudioSocket" in text
    assert "127.0.0.1:5060" in text
    assert "docker compose up" in text
    assert "No cloud PBX" in text
    assert "UDP only" in text
    assert "127.0.0.1:8088" in text
    assert "Stasis(rva)" in text
