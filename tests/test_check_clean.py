"""Guardrail tests for scripts/check_clean.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK_CLEAN = ROOT / "scripts" / "check_clean.py"


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECK_CLEAN), str(root)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_check_clean_passes_on_this_repo() -> None:
    result = _run(ROOT)
    assert result.returncode == 0, result.stderr


def test_check_clean_rejects_forbidden_brand(tmp_path: Path) -> None:
    (tmp_path / "leak.md").write_text("cata" + "litico", encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "forbidden name" in result.stderr


def test_check_clean_rejects_public_ipv4(tmp_path: Path) -> None:
    leaked = ".".join(["8", "8", "8", "8"])
    (tmp_path / "net.md").write_text(f"edge {leaked}", encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert leaked in result.stderr


def test_check_clean_allows_documentation_ipv4(tmp_path: Path) -> None:
    (tmp_path / "net.md").write_text("bind 192.0.2.10 and 127.0.0.1", encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
