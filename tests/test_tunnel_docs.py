"""HTTPS tunnel documentation (ngrok / Cloudflare) — no secrets in git, not in CI."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TUNNEL = ROOT / "colab" / "TUNNEL.md"
COLAB_README = ROOT / "colab" / "README.md"
NOTEBOOK = ROOT / "notebooks" / "colab_nemo_es.ipynb"
ENV_EXAMPLE = ROOT / ".env.example"
WORKFLOWS = ROOT / ".github" / "workflows"

_SECRET_NEEDLES = (
    "NGROK_AUTHTOKEN=",
    "CLOUDFLARE_TUNNEL_TOKEN=",
    "sk-",
    "github_pat_",
)


def test_tunnel_doc_covers_ngrok_and_cloudflare() -> None:
    text = TUNNEL.read_text(encoding="utf-8")
    assert "ngrok" in text.lower()
    assert "cloudflare" in text.lower() or "cloudflared" in text.lower()
    assert "RVA_COLAB_URL" in text
    assert "RVA_STT_URL" in text
    assert "RVA_TTS_URL" in text
    assert "RVA_STT_BACKEND=http" in text
    assert "RVA_TTS_BACKEND=http" in text
    assert "no trailing slash" in text
    assert "/v1/audio/transcriptions" in text
    assert "/v1/audio/speech" in text
    assert "cloudflared-linux-amd64" in text
    assert "trycloudflare" in text
    assert "!wget" in text
    assert '"tunnel", "run", "--token"' in text or "tunnel run --token" in text
    assert "`{url}/v1/audio/transcriptions`" not in text
    assert "https://\\S+" not in text
    assert "not in git" in text.lower() or "never commit" in text.lower()
    assert "Colab" in text and "Secret" in text
    assert "rva colab status" in text
    for needle in _SECRET_NEEDLES:
        assert needle not in text


def test_tunnel_doc_has_trailing_newline() -> None:
    assert TUNNEL.read_bytes().endswith(b"\n")


def test_colab_readme_links_tunnel_guide() -> None:
    text = COLAB_README.read_text(encoding="utf-8")
    assert "TUNNEL.md" in text
    assert "later docs issue" not in text


def test_notebook_references_tunnel_doc() -> None:
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    src = "".join("".join(c.get("source", [])) for c in nb["cells"])
    assert "TUNNEL.md" in src
    assert "NGROK_AUTHTOKEN" in src


def test_env_example_documents_colab_url_not_tunnel_secrets() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "RVA_COLAB_URL" in text
    assert "NGROK_AUTHTOKEN" not in text
    assert "CLOUDFLARE_TUNNEL_TOKEN" not in text


def test_ci_does_not_run_tunnel_tools() -> None:
    workflows = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    assert workflows, "expected at least one workflow under .github/workflows"
    merged = "\n".join(p.read_text(encoding="utf-8") for p in workflows)
    assert "services:" not in merged
    assert "container:" not in merged
    assert "python -m pytest" in merged
    for pattern in (
        r"\bngrok\b",
        r"\bcloudflared\b",
        r"\bcloudflare\s+tunnel\b",
    ):
        assert not re.search(pattern, merged, re.IGNORECASE)
