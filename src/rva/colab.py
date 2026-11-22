"""Colab worker health, RTT, exponential backoff, and STT/TTS fallback."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

_HTTP = "http"

_PROBE = Callable[[str, str | None, float], tuple[bool, float | None]]

_SHARED = None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


_OPENER = build_opener(_NoRedirect)


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
        with _OPENER.open(req, timeout=timeout_s) as resp:
            payload = resp.read()
            status = resp.status
    except HTTPError:
        rtt = (time.perf_counter() - t0) * 1000.0
        return False, rtt
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


def remote_stt_tts_requested() -> bool:
    """True when env points STT or TTS at HTTP backends (Colab path)."""
    for key in ("RVA_STT_BACKEND", "RVA_TTS_BACKEND"):
        raw = os.environ.get(key, "mock").strip().lower()
        if raw == _HTTP:
            return True
    return False


class ColabOrchestrator:
    """Probe ``RVA_COLAB_URL``; backoff on failure; pin HTTP STT/TTS during a call."""

    @classmethod
    def shared(cls) -> ColabOrchestrator:
        global _SHARED
        if _SHARED is None:
            _SHARED = cls()
        return _SHARED

    @classmethod
    def reset_shared_for_tests(cls) -> None:
        global _SHARED
        _SHARED = None

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
        if self._pinned_remote and self._in_call:
            return self._status_snapshot(backoff_remaining_s=max(0.0, self._backoff_until - now))
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


def activate_call_pin(orchestrator: ColabOrchestrator | None = None) -> None:
    """Pin remote STT/TTS for an active call (ARI / AudioSocket lifecycle)."""
    if not ColabOrchestrator.colab_configured():
        return
    orch = orchestrator or ColabOrchestrator.shared()
    if remote_stt_tts_requested():
        orch.enter_call(remote_stt_tts=True)


def release_call_pin(orchestrator: ColabOrchestrator | None = None) -> None:
    orch = orchestrator or ColabOrchestrator.shared()
    orch.leave_call()
