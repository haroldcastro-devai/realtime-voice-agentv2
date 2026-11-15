"""OpenAI-compatible HTTP STT / LLM / TTS clients (stdlib urllib only)."""

from __future__ import annotations

import json
import os
import struct
import uuid
from json import JSONDecodeError
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from rva.pipeline import BackendError
from rva.resample import resample_s16le

_FRAME_S16_8K = 320
_JSON = "application/json"
_OPENAI_TTS_PCM_HZ = 24_000
_SOCK_HZ = 8_000
_ERR_BODY_MAX = 200


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
        raise BackendError("RVA_HTTP_TIMEOUT must be a number") from exc
    if value <= 0:
        raise BackendError("RVA_HTTP_TIMEOUT must be a number")
    return value


def _require_url(env_key: str) -> str:
    url = _env(env_key)
    if url is None:
        raise BackendError(f"{env_key} must be set for the http backend")
    return url.rstrip("/")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise BackendError(f"HTTP {code} redirect rejected")


_OPENER = build_opener(_NoRedirect)


class HttpStt:
    """POST ``/v1/audio/transcriptions`` (WAV file + sample rate in the header)."""

    def __init__(self, base_url: str, token: str | None = None, model: str = "rva-stt") -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.model = model

    @classmethod
    def from_env(cls) -> HttpStt:
        return cls(
            _require_url("RVA_STT_URL"),
            token=_env("RVA_STT_TOKEN"),
            model=_env("RVA_STT_MODEL") or "rva-stt",
        )

    def transcribe(self, pcm: bytes, sample_rate: int = 16_000) -> str:
        wav = _pcm16_wav(pcm, sample_rate)
        boundary = "----rva" + uuid.uuid4().hex
        parts = [
            _form_field(boundary, "model", self.model),
            _form_file(boundary, "file", "audio.wav", wav, "audio/wav"),
        ]
        body = b"".join(parts) + f"--{boundary}--\r\n".encode()
        payload = _request(
            f"{self.base_url}/v1/audio/transcriptions",
            body,
            f"multipart/form-data; boundary={boundary}",
            self.token,
        )
        data = _load_json(payload)
        if not isinstance(data, dict):
            raise BackendError("STT response missing text")
        text = data.get("text")
        if not isinstance(text, str):
            raise BackendError("STT response missing text")
        return text


class HttpLlm:
    """POST ``/v1/chat/completions``."""

    def __init__(self, base_url: str, token: str | None = None, model: str = "rva-llm") -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.model = model

    @classmethod
    def from_env(cls) -> HttpLlm:
        return cls(
            _require_url("RVA_LLM_URL"),
            token=_env("RVA_LLM_TOKEN"),
            model=_env("RVA_LLM_MODEL") or "rva-llm",
        )

    def complete(self, text: str) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": text}],
            }
        ).encode()
        payload = _request(f"{self.base_url}/v1/chat/completions", body, _JSON, self.token)
        data = _load_json(payload)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise BackendError("LLM response missing choices[0].message.content") from exc
        if not isinstance(content, str):
            raise BackendError("LLM response missing choices[0].message.content")
        return content


class HttpTts:
    """POST ``/v1/audio/speech``. OpenAI ``pcm`` is 24 kHz; we resample to 8 kHz."""

    def __init__(self, base_url: str, token: str | None = None, model: str = "rva-tts") -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.model = model

    @classmethod
    def from_env(cls) -> HttpTts:
        return cls(
            _require_url("RVA_TTS_URL"),
            token=_env("RVA_TTS_TOKEN"),
            model=_env("RVA_TTS_MODEL") or "rva-tts",
        )

    def synthesize(self, text: str) -> bytes:
        body = json.dumps(
            {
                "model": self.model,
                "input": text,
                "voice": "ava",
                "response_format": "pcm",
            }
        ).encode()
        pcm24 = _request(f"{self.base_url}/v1/audio/speech", body, _JSON, self.token)
        if len(pcm24) % 2:
            pcm24 = pcm24 + b"\x00"
        pcm8 = resample_s16le(pcm24, _OPENAI_TTS_PCM_HZ, _SOCK_HZ)
        extra = len(pcm8) % _FRAME_S16_8K
        if extra:
            pcm8 = pcm8 + b"\x00" * (_FRAME_S16_8K - extra)
        if not pcm8:
            pcm8 = b"\x00" * _FRAME_S16_8K
        return pcm8


def _pcm16_wav(pcm: bytes, sample_rate: int) -> bytes:
    if sample_rate <= 0:
        raise BackendError("sample_rate must be positive")
    if len(pcm) % 2:
        pcm = pcm + b"\x00"
    data_len = len(pcm)
    return (
        b"RIFF"
        + struct.pack("<I", 36 + data_len)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
        + b"data"
        + struct.pack("<I", data_len)
        + pcm
    )


def _load_json(payload: bytes) -> object:
    try:
        return json.loads(payload.decode("utf-8"))
    except (JSONDecodeError, UnicodeDecodeError) as exc:
        raise BackendError("HTTP JSON response is invalid") from exc


def _form_field(boundary: str, name: str, value: str) -> bytes:
    return (
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
    ).encode()


def _form_file(boundary: str, name: str, filename: str, data: bytes, content_type: str) -> bytes:
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode()
    return head + data + b"\r\n"


def _request(url: str, body: bytes, content_type: str, token: str | None) -> bytes:
    headers = {"Content-Type": content_type, "Accept": "*/*"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=body, headers=headers, method="POST")
    try:
        with _OPENER.open(req, timeout=_timeout()) as resp:
            return resp.read()
    except HTTPError as exc:
        snippet = exc.read()[:_ERR_BODY_MAX]
        raise BackendError(f"HTTP {exc.code} from {url}: {snippet!r}") from exc
    except TimeoutError as exc:
        raise BackendError(f"HTTP timeout from {url}") from exc
    except URLError as exc:
        raise BackendError(f"HTTP client failed: {exc.reason}") from exc
