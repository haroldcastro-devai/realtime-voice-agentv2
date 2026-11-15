"""OpenAI-compatible HTTP STT / LLM / TTS clients (stdlib urllib only)."""

from __future__ import annotations

import json
import os
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from rva.pipeline import BackendError

_FRAME_S16_8K = 320
_JSON = "application/json"


def _env(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None or raw == "" or raw == "CHANGE_ME":
        return None
    return raw


def _timeout() -> float:
    raw = _env("RVA_HTTP_TIMEOUT")
    if raw is None:
        return 10.0
    return float(raw)


def _require_url(env_key: str) -> str:
    url = _env(env_key)
    if url is None:
        raise BackendError(f"{env_key} must be set for the http backend")
    return url.rstrip("/")


class HttpStt:
    """POST ``/v1/audio/transcriptions`` (multipart file)."""

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
        boundary = "----rva" + uuid.uuid4().hex
        filename = "audio.raw"
        parts = [
            _form_field(boundary, "model", self.model),
            _form_file(boundary, "file", filename, pcm, "application/octet-stream"),
        ]
        body = b"".join(parts) + f"--{boundary}--\r\n".encode()
        payload = _request(
            f"{self.base_url}/v1/audio/transcriptions",
            body,
            f"multipart/form-data; boundary={boundary}",
            self.token,
        )
        text = json.loads(payload.decode()).get("text")
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
        data = json.loads(payload.decode())
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise BackendError("LLM response missing choices[0].message.content") from exc
        if not isinstance(content, str):
            raise BackendError("LLM response missing choices[0].message.content")
        return content


class HttpTts:
    """POST ``/v1/audio/speech``; body is 8 kHz s16le (padded to 20 ms frames)."""

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
        pcm = _request(f"{self.base_url}/v1/audio/speech", body, _JSON, self.token)
        if len(pcm) % 2:
            pcm = pcm + b"\x00"
        extra = len(pcm) % _FRAME_S16_8K
        if extra:
            pcm = pcm + b"\x00" * (_FRAME_S16_8K - extra)
        if not pcm:
            pcm = b"\x00" * _FRAME_S16_8K
        return pcm


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
        with urlopen(req, timeout=_timeout()) as resp:
            return resp.read()
    except HTTPError as exc:
        raise BackendError(f"HTTP {exc.code} from {url}") from exc
    except URLError as exc:
        raise BackendError(f"HTTP client failed: {exc.reason}") from exc
