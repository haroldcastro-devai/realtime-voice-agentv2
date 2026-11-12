"""Smoke tests for the empty package scaffold."""

from importlib.metadata import version

from rva import __version__


def test_package_version_is_semver_like() -> None:
    parts = __version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)


def test_package_is_importable() -> None:
    import rva

    assert rva.__version__ == __version__


def test_installed_version_matches_package() -> None:
    assert version("realtime-voice-agentv2") == __version__
