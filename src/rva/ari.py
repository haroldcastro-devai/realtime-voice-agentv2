"""ARI application hook: StasisStart creates a CallSession (stdlib urllib).

Does not open a WebSocket in tests. ``register()`` checks ARI over HTTP and
returns the events URL. ``handle_event`` is the Stasis dispatcher.
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Callable
from json import JSONDecodeError
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from rva.session import CallSession

_APP = "rva"


class AriError(ValueError):
    """ARI URL, auth, or event mapping failed."""


class AriRest(Protocol):
    def continue_channel(self, channel_id: str, context: str, exten: str) -> None: ...


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
    except ValueError as exc:
        raise AriError("RVA_HTTP_TIMEOUT must be a number") from exc
    if value <= 0:
        raise AriError("RVA_HTTP_TIMEOUT must be a number")
    return value


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise AriError(f"HTTP {code} redirect rejected")


_OPENER = build_opener(_NoRedirect)


class AriClient:
    """Loopback ARI REST + events URL for app ``rva``."""

    def __init__(self, base_url: str, user: str, password: str, app: str = _APP) -> None:
        self.base_url = base_url.rstrip("/")
        self.user = user
        self.password = password
        self.app = app

    @classmethod
    def from_env(cls) -> AriClient:
        url = _env("RVA_ARI_URL")
        user = _env("RVA_ARI_USER")
        password = _env("RVA_ARI_PASSWORD")
        if url is None:
            raise AriError("RVA_ARI_URL must be set")
        if user is None or password is None:
            raise AriError("RVA_ARI_USER and RVA_ARI_PASSWORD must be set")
        return cls(url, user, password, app=_env("RVA_ARI_APP") or _APP)

    def events_url(self) -> str:
        query = urlencode({"app": self.app, "api_key": f"{self.user}:{self.password}"})
        return f"{self.base_url}/ari/events?{query}"

    def register(self) -> str:
        """GET /ari/asterisk/info with basic auth. Returns the events URL."""
        self._get("/ari/asterisk/info")
        return self.events_url()

    def continue_channel(self, channel_id: str, context: str, exten: str) -> None:
        path = f"/ari/channels/{channel_id}/continue"
        query = urlencode({"context": context, "extension": exten, "priority": "1"})
        self._post(f"{path}?{query}")

    def _headers(self) -> dict[str, str]:
        token = base64.b64encode(f"{self.user}:{self.password}".encode()).decode("ascii")
        return {"Authorization": f"Basic {token}"}

    def _get(self, path: str) -> dict[str, object]:
        req = Request(self.base_url + path, headers=self._headers(), method="GET")
        return self._json(req)

    def _post(self, path: str) -> None:
        req = Request(self.base_url + path, data=b"", headers=self._headers(), method="POST")
        self._json(req, allow_empty=True)

    def _json(self, req: Request, allow_empty: bool = False) -> dict[str, object]:
        try:
            with _OPENER.open(req, timeout=_timeout()) as resp:
                raw = resp.read()
        except HTTPError as exc:
            body = exc.read()[:200] if exc.fp is not None else b""
            raise AriError(f"HTTP {exc.code} from {req.full_url}: {body!r}") from exc
        except (URLError, TimeoutError) as exc:
            raise AriError(str(exc)) from exc
        if not raw:
            if allow_empty:
                return {}
            raise AriError("empty ARI response")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (JSONDecodeError, UnicodeDecodeError) as exc:
            raise AriError("ARI response is not JSON") from exc
        if not isinstance(data, dict):
            raise AriError("ARI response is not JSON")
        return data


class AriApp:
    """Maps StasisStart to a new ``CallSession``; StasisEnd drops it."""

    def __init__(
        self,
        rest: AriRest | None = None,
        session_factory: Callable[[], CallSession] = CallSession,
        continue_context: str = "audiosocket",
        continue_exten: str = "s",
    ) -> None:
        self.rest = rest
        self._factory = session_factory
        self.continue_context = continue_context
        self.continue_exten = continue_exten
        self.sessions: dict[str, CallSession] = {}

    def handle_event(self, event: dict[str, object]) -> CallSession | None:
        etype = event.get("type")
        if etype == "StasisStart":
            channel = event.get("channel")
            if not isinstance(channel, dict):
                raise AriError("StasisStart missing channel")
            channel_id = channel.get("id")
            if not isinstance(channel_id, str) or not channel_id:
                raise AriError("StasisStart missing channel id")
            session = self._factory()
            self.sessions[channel_id] = session
            if self.rest is not None:
                self.rest.continue_channel(channel_id, self.continue_context, self.continue_exten)
            return session
        if etype == "StasisEnd":
            channel = event.get("channel")
            if isinstance(channel, dict):
                channel_id = channel.get("id")
                if isinstance(channel_id, str):
                    self.sessions.pop(channel_id, None)
            return None
        return None
