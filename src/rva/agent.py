"""Single-process agent: ARI events, AudioSocket, optional dashboard."""

from __future__ import annotations

import threading
import time
from http.server import ThreadingHTTPServer

from rva.ari import AriApp, AriClient, AriError
from rva.ari_events import iter_ari_events
from rva.audiosocket_server import AudioSocketServer, audiosocket_bind
from rva.colab import ColabOrchestrator
from rva.dashboard import dashboard_url, serve_dashboard, shutdown_server
from rva.pipeline import Pipeline, build_pipeline


class AgentRuntime:
    """Co-starts dashboard, AudioSocket TCP, and ARI Stasis dispatch."""

    def __init__(
        self,
        *,
        client: AriClient | None = None,
        app: AriApp | None = None,
        pipeline: Pipeline | None = None,
        with_dashboard: bool = True,
    ) -> None:
        self._client = client
        self._app = app
        self._pipeline = pipeline
        self._with_dashboard = with_dashboard
        self._stop = threading.Event()
        self._started = False
        self._startup_info: dict[str, object] = {}
        self._pipeline_lock = threading.Lock()
        self._dashboard: ThreadingHTTPServer | None = None
        self._audio: AudioSocketServer | None = None

    def start(self) -> dict[str, object]:
        if self._started:
            return dict(self._startup_info)
        client = self._client if self._client is not None else AriClient.from_env()
        app = self._app if self._app is not None else AriApp(rest=client)
        pipeline = (
            self._pipeline
            if self._pipeline is not None
            else build_pipeline(orchestrator=ColabOrchestrator.shared())
        )
        self._client = client
        self._app = app
        self._pipeline = pipeline
        events_url = client.register()
        payload: dict[str, object] = {"ari_events": events_url}
        host, port = audiosocket_bind()
        payload["audiosocket_listen"] = f"{host}:{port}"
        if self._with_dashboard:
            self._dashboard = serve_dashboard()
            dash_host, dash_port = self._dashboard.server_address[:2]
            payload["dashboard_url"] = dashboard_url(dash_host, dash_port)
            threading.Thread(target=self._dashboard.serve_forever, daemon=True).start()
        self._audio = AudioSocketServer(app, pipeline, pipeline_lock=self._pipeline_lock)
        self._audio.verify_bind()
        threading.Thread(
            target=self._audio.serve_forever,
            args=(self._stop,),
            daemon=True,
        ).start()
        threading.Thread(target=self._ari_event_loop, daemon=True).start()
        self._started = True
        self._startup_info = payload
        return payload

    def _ari_event_loop(self) -> None:
        client = self._client
        app = self._app
        if client is None or app is None:
            return
        while not self._stop.is_set():
            try:
                for event in iter_ari_events(client):
                    if self._stop.is_set():
                        break
                    app.handle_event(event)
            except (AriError, OSError):
                if self._stop.is_set():
                    return
                time.sleep(1.0)

    def stop(self) -> None:
        self._stop.set()
        if self._dashboard is not None:
            shutdown_server(self._dashboard)
            self._dashboard = None
        if self._audio is not None:
            self._audio.close_listener()

    def run_until_interrupt(self) -> int:
        if not self._started:
            self.start()
        try:
            while not self._stop.wait(3600.0):
                pass
        except KeyboardInterrupt:
            self.stop()
        return 0
