"""Smoke tests for the empty package scaffold."""

from rva import __version__


def test_package_version_is_semver_like() -> None:
    parts = __version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)


def test_package_is_importable() -> None:
    import rva

    assert rva.__version__ == __version__
