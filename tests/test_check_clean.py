"""Guardrail tests for scripts/check_clean.py."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECK_CLEAN = ROOT / "scripts" / "check_clean.py"
CHECK_CLEAN_SH = ROOT / "scripts" / "check_clean.sh"


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
    assert "rule=name" in result.stderr
    assert "cata" + "litico" not in result.stderr.lower()


def test_check_clean_rejects_carrier_token(tmp_path: Path) -> None:
    (tmp_path / "leak.md").write_text("cla" + "ro", encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "rule=name" in result.stderr


def test_check_clean_rejects_secret_pattern(tmp_path: Path) -> None:
    token = "AKIA" + ("0" * 16)
    (tmp_path / ".env.local").write_text(token, encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "rule=secret" in result.stderr
    assert token not in result.stderr


def test_check_clean_rejects_pem_key_name(tmp_path: Path) -> None:
    (tmp_path / "id.pem").write_text("-----BEGIN " + "PRIVATE KEY-----\n", encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "rule=secret" in result.stderr


def test_check_clean_rejects_public_ipv4(tmp_path: Path) -> None:
    leaked = ".".join(["8", "8", "8", "8"])
    (tmp_path / "net.md").write_text(f"edge {leaked}", encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert leaked in result.stderr
    assert "rule=ip" in result.stderr


def test_check_clean_allows_documentation_ipv4(tmp_path: Path) -> None:
    (tmp_path / "net.md").write_text(
        "bind 192.0.2.10 and 127.0.0.1 and 203.0.113.10",
        encoding="utf-8",
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr


def test_shell_wrapper_passes_on_this_repo() -> None:
    if sys.platform == "win32":
        pytest.skip("bash wrapper is exercised on Linux CI")
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not on PATH")
    result = subprocess.run(
        [bash, str(CHECK_CLEAN_SH)],
        check=False,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
