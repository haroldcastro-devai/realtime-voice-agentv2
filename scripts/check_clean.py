#!/usr/bin/env python3
"""Fail if the tree contains employer, carrier, secret, or documentation-IP leaks.

Needles are assembled at runtime so this file does not store brand strings whole.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".egg-info",
}
SKIP_SUFFIXES = {".pyc", ".pyo", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".zip", ".whl"}
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".toml",
    ".yml",
    ".yaml",
    ".sh",
    ".txt",
    ".cfg",
    ".ini",
    ".json",
    ".example",
    ".gitignore",
    "",
}

IPV4_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\b")

SECRET_RES = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def _name_needles() -> tuple[re.Pattern[str], ...]:
    brands = (
        "cata" + "litico",
        "cata" + "lítico",
        "natal" + "ia",
        "eco" + "origen",
        "py" + "origen",
    )
    patterns = [re.compile(re.escape(b), re.IGNORECASE) for b in brands]
    patterns.append(re.compile(r"\bo" + r"cm\b", re.IGNORECASE))
    patterns.append(re.compile(r"\bcla" + r"ro\b", re.IGNORECASE))
    patterns.append(re.compile("cata" + r"litico-dev\.atlassian\.net", re.IGNORECASE))
    return tuple(patterns)


NAME_RES = _name_needles()


def _ip_allowed(ip: str) -> bool:
    parts = [int(p) for p in ip.split(".")]
    a, b = parts[0], parts[1]
    if ip in {"0.0.0.0", "127.0.0.1", "255.255.255.255"}:
        return True
    if a == 10:
        return True
    if a == 127:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 192 and b == 168:
        return True
    if a == 192 and b == 0 and parts[2] == 2:
        return True
    if a == 198 and b == 51 and parts[2] == 100:
        return True
    if a == 203 and b == 113:
        return True
    return False


def _iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES or part.endswith(".egg-info") for part in path.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {
            ".gitignore",
            ".env.example",
        }:
            continue
        files.append(path)
    return files


def scan(root: Path) -> list[str]:
    hits: list[str] = []
    for path in _iter_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = path.relative_to(root).as_posix()
        for rx in NAME_RES:
            if rx.search(text):
                hits.append(f"{rel}: forbidden name/token matching /{rx.pattern}/")
        for rx in SECRET_RES:
            if rx.search(text):
                hits.append(f"{rel}: secret-like pattern matching /{rx.pattern}/")
        for ip in IPV4_RE.findall(text):
            if not _ip_allowed(ip):
                hits.append(f"{rel}: non-documentation IPv4 {ip}")
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".", help="Repository root to scan")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    hits = scan(root)
    if hits:
        print("check_clean failed:", file=sys.stderr)
        for hit in hits:
            print(f"  {hit}", file=sys.stderr)
        return 1
    print("check_clean: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
