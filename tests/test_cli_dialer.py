"""CLI dialer originate: structured errors without tracebacks."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest

from rva.cli import main


def test_dialer_originate_reports_missing_ari_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_path = tmp_path / "ok.csv"
    csv_path.write_text("msisdn,name\n+57 300 000 0001,x\n", encoding="utf-8")
    monkeypatch.delenv("RVA_ARI_URL", raising=False)
    monkeypatch.setenv("RVA_ARI_USER", "rva")
    monkeypatch.setenv("RVA_ARI_PASSWORD", "rva-ari-demo")
    out = StringIO()
    monkeypatch.setattr("sys.stdout", out)
    code = main(["dialer", "originate", "--csv", str(csv_path)])
    assert code == 1
    payload = json.loads(out.getvalue())
    assert "error" in payload
    assert payload["originated"] == []
    assert "RVA_ARI_URL" in payload["error"]
