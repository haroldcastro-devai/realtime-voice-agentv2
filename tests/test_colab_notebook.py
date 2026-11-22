"""Colab NeMo notebook + server: static checks only (no GPU, no Colab in CI)."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "colab_nemo_es.ipynb"
SERVER = ROOT / "colab" / "nemo_server.py"
README = ROOT / "colab" / "README.md"
CI = ROOT / ".github" / "workflows" / "ci.yml"

_FORBIDDEN_KEEPALIVE = (
    "display.javascript",
    "setinterval",
    "keep_alive",
    "prevent_disconnect",
    "autoclick",
)


def _notebook_source() -> str:
    data = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    chunks: list[str] = []
    for cell in data.get("cells", []):
        chunks.append("".join(cell.get("source", [])))
    return "\n".join(chunks)


def test_notebook_spanish_nemo_bearer_and_https() -> None:
    text = _notebook_source()
    lowered = text.lower()
    assert "tts_es_fastpitch_multispeaker" in text
    assert "from_pretrained" in text
    assert "tts_es_hifigan" in text
    assert "secrets.token_urlsafe" in text
    assert "bearer" in lowered or "INFERENCE_TOKEN" in text
    assert "https://" in text
    assert "RVA_COLAB_URL" in text
    assert "RVA_COLAB_TOKEN" in text
    for needle in _FORBIDDEN_KEEPALIVE:
        assert needle not in lowered


def test_nemo_server_openai_routes_and_spanish_defaults() -> None:
    text = SERVER.read_text(encoding="utf-8")
    assert "tts_es_fastpitch_multispeaker" in text
    assert "tts_es_hifigan" in text
    assert "/v1/audio/transcriptions" in text
    assert "/v1/audio/speech" in text
    assert "Bearer" in text
    assert "Do not import this module from" in text


def test_colab_readme_and_ci_skip_gpu() -> None:
    doc = README.read_text(encoding="utf-8")
    assert "colab_nemo_es.ipynb" in doc
    assert "Colab terms" in doc
    assert "idle" in doc.lower()
    ci = CI.read_text(encoding="utf-8")
    assert not re.search(r"\bnemo_toolkit\b", ci, re.IGNORECASE)
    assert not re.search(r"\bcolab\b", ci, re.IGNORECASE)
