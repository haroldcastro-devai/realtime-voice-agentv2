"""GPU NeMo STT/TTS for Google Colab only.

Local agent PCs use ``rva.http_backends`` against these OpenAI-shaped routes.
Do not import this module from ``src/rva``.
"""

from __future__ import annotations

import io
import os
import wave
from functools import lru_cache

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

TOKEN = os.environ.get("INFERENCE_TOKEN", "")
ASR_NAME = os.environ.get("NEMO_ASR_MODEL", "nvidia/stt_es_conformer_ctc_large")
TTS_SPEC_NAME = os.environ.get("NEMO_TTS_SPEC", "tts_es_fastpitch_multispeaker")
TTS_VOCODER_NAME = os.environ.get("NEMO_TTS_VOCODER", "tts_es_hifigan")
_TTS_PCM_HZ = 24_000

app = FastAPI(title="NeMo Colab worker (Acme Telco / Ava)", version="0.1.0")


def _auth(authorization: str | None) -> None:
    if not TOKEN:
        return
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


@lru_cache
def asr_model():
    import nemo.collections.asr as nemo_asr

    return nemo_asr.models.ASRModel.from_pretrained(ASR_NAME)


@lru_cache
def tts_models():
    from nemo.collections.tts.models import FastPitchModel, HifiGanModel

    spec = FastPitchModel.from_pretrained(TTS_SPEC_NAME).eval().cuda()
    vocoder = HifiGanModel.from_pretrained(TTS_VOCODER_NAME).eval().cuda()
    return spec, vocoder


class TtsIn(BaseModel):
    model: str = "rva-tts"
    input: str = ""
    voice: str = "ava"
    response_format: str = "pcm"


def _wav_bytes_to_path(raw: bytes) -> str:
    audio, rate = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
    if getattr(audio, "ndim", 1) > 1:
        audio = np.mean(audio, axis=1)
    path = "/tmp/rva_utt.wav"
    sf.write(path, audio, rate)
    return path


def _transcribe_wav(raw: bytes) -> str:
    path = _wav_bytes_to_path(raw)
    text = asr_model().transcribe([path])[0]
    if hasattr(text, "text"):
        text = text.text
    return str(text).strip()


def _synthesize_pcm(text: str) -> bytes:
    spec, vocoder = tts_models()
    parsed = spec.parse(text or "hola")
    spectrogram = spec.generate_spectrogram(tokens=parsed)
    audio = vocoder.convert_spectrogram_to_audio(spec=spectrogram)
    wav = audio.to("cpu").detach().numpy().flatten().astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, wav, _TTS_PCM_HZ, format="WAV", subtype="PCM_16")
    return _wav_to_pcm_s16le(buf.getvalue())


def _wav_to_pcm_s16le(raw: bytes) -> bytes:
    with wave.open(io.BytesIO(raw), "rb") as w:
        if w.getsampwidth() != 2:
            raise HTTPException(status_code=500, detail="unexpected wav width")
        rate = w.getframerate()
        frames = w.readframes(w.getnframes())
    if rate != _TTS_PCM_HZ:
        raise HTTPException(status_code=500, detail="unexpected wav rate")
    return frames


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "ok": "true",
        "asr": ASR_NAME,
        "tts_spec": TTS_SPEC_NAME,
        "tts_vocoder": TTS_VOCODER_NAME,
    }


@app.post("/v1/audio/transcriptions")
async def openai_stt(
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    _auth(authorization)
    text = _transcribe_wav(await file.read())
    return {"text": text}


@app.post("/v1/audio/speech")
async def openai_tts(body: TtsIn, authorization: str | None = Header(default=None)) -> Response:
    _auth(authorization)
    if body.response_format not in ("pcm", "wav"):
        raise HTTPException(status_code=400, detail="unsupported response_format")
    pcm = _synthesize_pcm(body.input)
    return Response(content=pcm, media_type="application/octet-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
