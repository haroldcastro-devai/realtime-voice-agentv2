"""Colab worker health, RTT, exponential backoff, and STT/TTS fallback."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import Request, urlopen

_PROBE = Callable[[str, str | None, float], tuple[bool, float | None]]


def _env(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None or raw == "" or raw == "CHANGE_ME":
        return None
    return raw


def _timeout() -> float:
    raw = _env("RVA_HTTP_TIMEOUT")
    if raw is None:
        return 10.0
    try:
        value = float(raw)
    except ValueError:
        return 10.0
    return value if value > 0 else 10.0


def _backoff_cap() -> float:
    raw = _env("RVA_COLAB_BACKOFF_MAX_S")
    if raw is None:
        return 60.0
    try:
        value = float(raw)
    except ValueError:
        return 60.0
    return max(1.0, value)


def backoff_seconds(failures: int, *, cap_s: float | None = None) -> float:
    """Exponential backoff capped at ``cap_s`` (default ``RVA_COLAB_BACKOFF_MAX_S``)."""
    if failures <= 0:
        return 0.0
    cap = _backoff_cap() if cap_s is None else cap_s
    return min(cap, float(2 ** min(failures, 6)))


def probe_colab_health(
    base_url: str,
    token: str | None,
    timeout_s: float,
) -> tuple[bool, float | None]:
    """GET ``/health``; return ``(ok, rtt_ms)``."""
    url = base_url.rstrip("/") + "/health"
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers, method="GET")
    t0 = time.perf_counter()
    try:
        with urlopen(req, timeout=timeout_s) as resp:
            payload = resp.read()
            status = resp.status
    except (TimeoutError, URLError, OSError):
        rtt = (time.perf_counter() - t0) * 1000.0
        return False, rtt
    rtt = (time.perf_counter() - t0) * 1000.0
    if status != 200:
        return False, rtt
    try:
        data = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False, rtt
    ok = isinstance(data, dict) and str(data.get("ok", "")).lower() == "true"
    return ok, rtt


@dataclass(frozen=True, slots=True)
class ColabStatus:
    configured: bool
    health_ok: bool
    rtt_ms: float | None
    consecutive_failures: int
    backoff_remaining_s: float
    fallback_stt_tts: bool
    in_call: bool
    pinned_remote: bool


class ColabOrchestrator:
    """Probe ``RVA_COLAB_URL``; backoff on failure; pin HTTP STT/TTS during a call."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        probe: _PROBE = probe_colab_health,
    ) -> None:
        self._clock = clock
        self._probe = probe
        self._failures = 0
        self._backoff_until = 0.0
        self._in_call = False
        self._pinned_remote = False
        self._last_health_ok = False
        self._last_rtt_ms: float | None = None

    @staticmethod
    def colab_configured() -> bool:
        return _env("RVA_COLAB_URL") is not None

    def enter_call(self, *, remote_stt_tts: bool) -> None:
        self._in_call = True
        if remote_stt_tts:
            self._pinned_remote = True

    def leave_call(self) -> None:
        self._in_call = False
        self._pinned_remote = False

    def refresh(self) -> ColabStatus:
        if not self.colab_configured():
            return ColabStatus(
                configured=False,
                health_ok=False,
                rtt_ms=None,
                consecutive_failures=0,
                backoff_remaining_s=0.0,
                fallback_stt_tts=False,
                in_call=self._in_call,
                pinned_remote=self._pinned_remote,
            )
        now = self._clock()
        if now < self._backoff_until and not self._pinned_remote:
            return self._status_snapshot(backoff_remaining_s=self._backoff_until - now)
        url = _env("RVA_COLAB_URL")
        token = _env("RVA_COLAB_TOKEN")
        assert url is not None
        ok, rtt = self._probe(url, token, _timeout())
        self._last_rtt_ms = rtt
        if ok:
            self._failures = 0
            self._backoff_until = 0.0
            self._last_health_ok = True
        else:
            self._failures += 1
            self._backoff_until = now + backoff_seconds(self._failures)
            self._last_health_ok = False
        return self._status_snapshot(backoff_remaining_s=max(0.0, self._backoff_until - now))

    def use_remote_stt_tts(self) -> bool:
        """Whether STT/TTS should stay on HTTP (Colab) vs fall back to mocks."""
        if not self.colab_configured():
            return True
        if self._pinned_remote and self._in_call:
            return True
        if self._clock() < self._backoff_until:
            return False
        return self._last_health_ok

    def _status_snapshot(self, *, backoff_remaining_s: float) -> ColabStatus:
        configured = self.colab_configured()
        fallback = configured and not self.use_remote_stt_tts()
        return ColabStatus(
            configured=configured,
            health_ok=self._last_health_ok,
            rtt_ms=self._last_rtt_ms,
            consecutive_failures=self._failures,
            backoff_remaining_s=backoff_remaining_s,
            fallback_stt_tts=fallback,
            in_call=self._in_call,
            pinned_remote=self._pinned_remote,
        )
