"""TCP AudioSocket listener: UUID match, pipeline turns, CALL_BUFFER."""

from __future__ import annotations

import os
import socket
import threading
import uuid
from typing import Protocol

from rva.ari import AriApp
from rva.audiosocket import FrameError, split_frame
from rva.inbound_queue import InboundQueue
from rva.pipeline import Pipeline
from rva.recordings import CALL_BUFFER
from rva.session import CallSession
from rva.tx import Clock
from rva.utterance import UtteranceCollector


class AudioSocketError(ValueError):
    """Bind or UUID resolution failed."""


def _env_host() -> str:
    raw = os.environ.get("RVA_AUDIOSOCKET_HOST", "0.0.0.0")
    if raw in ("", "CHANGE_ME"):
        return "0.0.0.0"
    return raw


def _env_port() -> int:
    raw = os.environ.get("RVA_AUDIOSOCKET_PORT", "8090")
    try:
        return int(raw)
    except ValueError:
        return 8090


def audiosocket_bind() -> tuple[str, int]:
    return _env_host(), _env_port()


class StopFlag(Protocol):
    def is_set(self) -> bool: ...


def _read_until_uuid(sock: socket.socket, timeout_s: float) -> str | None:
    sock.settimeout(timeout_s)
    buffer = b""
    while True:
        try:
            chunk = sock.recv(4096)
        except TimeoutError:
            return None
        except OSError:
            return None
        if not chunk:
            return None
        buffer += chunk
        try:
            while True:
                frame, buffer = split_frame(buffer)
                if frame is None:
                    break
                if frame.is_uuid:
                    return str(uuid.UUID(bytes=frame.payload))
                if frame.is_hangup:
                    return None
        except FrameError:
            return None


def _reader_loop(
    sock: socket.socket,
    inbound: InboundQueue,
    session: CallSession,
    channel_id: str,
    stop: threading.Event,
    read_poll_s: float,
) -> None:
    buffer = b""
    sock.settimeout(read_poll_s)
    while not stop.is_set():
        try:
            chunk = sock.recv(4096)
        except TimeoutError:
            continue
        except OSError:
            stop.set()
            inbound.close()
            return
        if not chunk:
            stop.set()
            inbound.close()
            return
        buffer += chunk
        try:
            while True:
                frame, buffer = split_frame(buffer)
                if frame is None:
                    break
                if frame.is_hangup:
                    stop.set()
                    inbound.close()
                    return
                if frame.is_pcm and frame.payload:
                    CALL_BUFFER.append_pcm(channel_id, frame.payload)
                    inbound.push(frame)
        except FrameError:
            stop.set()
            inbound.close()
            return


def run_audiosocket_call(
    sock: socket.socket,
    *,
    ari_app: AriApp,
    pipeline: Pipeline,
    channel_id: str,
    session: CallSession,
    read_timeout_s: float = 60.0,
    clock: Clock | None = None,
    pipeline_lock: threading.Lock | None = None,
) -> None:
    """Pipeline + paced TX for one established AudioSocket connection."""
    stop = threading.Event()
    inbound = InboundQueue()
    poll_s = min(0.5, read_timeout_s)
    reader = threading.Thread(
        target=_reader_loop,
        args=(sock, inbound, session, channel_id, stop, poll_s),
        daemon=True,
    )
    reader.start()
    collector = UtteranceCollector()
    try:
        while not stop.is_set():
            utterance = _collect_utterance(inbound, collector, stop, timeout_s=poll_s)
            if stop.is_set():
                break
            if not utterance:
                continue
            if pipeline_lock is not None:
                with pipeline_lock:
                    turn = pipeline.turn(utterance)
            else:
                turn = pipeline.turn(utterance)
            session.play_on(
                turn.tts_pcm,
                inbound.iter_open(stop),
                sock,
                clock=clock,
                drain_inbound_after=False,
            )
    finally:
        stop.set()
        inbound.close()
        reader.join(timeout=2.0)


def _collect_utterance(
    inbound: InboundQueue,
    collector: UtteranceCollector,
    stop: threading.Event,
    *,
    timeout_s: float = 0.1,
) -> bytes | None:
    while not stop.is_set():
        frame = inbound.get(timeout=timeout_s)
        if frame is None:
            continue
        if frame.is_pcm and frame.payload:
            done = collector.feed_pcm8k(frame.payload)
            if done:
                return done
    return None


class AudioSocketServer:
    """Accept AudioSocket TCP connections and run :func:`run_audiosocket_call`."""

    def __init__(
        self,
        ari_app: AriApp,
        pipeline: Pipeline,
        *,
        host: str | None = None,
        port: int | None = None,
        accept_timeout_s: float = 1.0,
        call_read_timeout_s: float = 60.0,
        pipeline_lock: threading.Lock | None = None,
    ) -> None:
        bind_host, bind_port = audiosocket_bind()
        self._host = host if host is not None else bind_host
        self._port = port if port is not None else bind_port
        self._ari_app = ari_app
        self._pipeline = pipeline
        self._accept_timeout_s = accept_timeout_s
        self._call_read_timeout_s = call_read_timeout_s
        self._pipeline_lock = pipeline_lock
        self._listener: socket.socket | None = None

    @property
    def address(self) -> tuple[str, int]:
        return self._host, self._port

    def verify_bind(self) -> None:
        """Fail fast when the listen address is not available."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((self._host, self._port))
            except OSError as exc:
                raise AudioSocketError(str(exc)) from exc

    def close_listener(self) -> None:
        listener = self._listener
        if listener is None:
            return
        try:
            listener.close()
        except OSError:
            pass
        self._listener = None

    def serve_forever(self, stop: StopFlag | None = None) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((self._host, self._port))
        except OSError as exc:
            listener.close()
            raise AudioSocketError(str(exc)) from exc
        listener.listen(8)
        listener.settimeout(self._accept_timeout_s)
        self._listener = listener
        try:
            while stop is None or not stop.is_set():
                try:
                    conn, _addr = listener.accept()
                except TimeoutError:
                    continue
                except OSError:
                    break
                thread = threading.Thread(
                    target=self._handle_client,
                    args=(conn,),
                    daemon=True,
                )
                thread.start()
        finally:
            listener.close()
            if self._listener is listener:
                self._listener = None

    def _handle_client(self, conn: socket.socket) -> None:
        try:
            with conn:
                socket_uuid = _read_until_uuid(conn, timeout_s=self._call_read_timeout_s)
                if socket_uuid is None:
                    return
                channel_id = self._ari_app.channel_for_socket_uuid(socket_uuid)
                if channel_id is None:
                    return
                session = self._ari_app.sessions.get(channel_id)
                if session is None:
                    return
                run_audiosocket_call(
                    conn,
                    ari_app=self._ari_app,
                    pipeline=self._pipeline,
                    channel_id=channel_id,
                    session=session,
                    read_timeout_s=self._call_read_timeout_s,
                    pipeline_lock=self._pipeline_lock,
                )
        except OSError:
            return
