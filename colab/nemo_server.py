"""GPU NeMo STT/TTS for Google Colab only.

Local agent PCs use ``rva.http_backends`` against these OpenAI-shaped routes.
Do not import this module from ``src/rva``.
"""

from __future__ import annotations

import io
import os
import uuid
import wave
from functools import lru_cache

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from audio_util import NEMO_TTS_HZ, OPENAI_PCM_HZ, resample_pcm16, speaker_id_from_voice

TOKEN = os.environ.get("INFERENCE_TOKEN", "")
ASR_NAME = os.environ.get("NEMO_ASR_MODEL", "nvidia/stt_es_conformer_ctc_large")
TTS_SPEC_NAME = os.environ.get("NEMO_TTS_SPEC", "tts_es_fastpitch_multispeaker")
TTS_VOCODER_NAME = os.environ.get(
    "NEMO_TTS_VOCODER",
    "tts_es_hifigan_ft_fastpitch_multispeaker",
)

_WARM_ASR: object | None = None
_WARM_SPEC: object | None = None
_WARM_VOC: object | None = None

app = FastAPI(title="NeMo Colab worker (Acme Telco / Ava)", version="0.1.0")


def warm_models(
    *,
    asr: object | None = None,
    spec: object | None = None,
    vocoder: object | None = None,
) -> None:
    """Reuse models already loaded in the notebook (avoids double ``from_pretrained``)."""
    global _WARM_ASR, _WARM_SPEC, _WARM_VOC
    if asr is not None:
        _WARM_ASR = asr
    if spec is not None and vocoder is not None:
        _WARM_SPEC = spec
        _WARM_VOC = vocoder


def ensure_models_loaded() -> None:
    """Load ASR + TTS if not warmed from the notebook."""
    asr_model()
    tts_models()


def _auth(authorization: str | None) -> None:
    if not TOKEN:
        raise HTTPException(status_code=500, detail="INFERENCE_TOKEN not configured")
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


@lru_cache
def asr_model():
    if _WARM_ASR is not None:
        return _WARM_ASR
    import nemo.collections.asr as nemo_asr

    return nemo_asr.models.ASRModel.from_pretrained(ASR_NAME)


@lru_cache
def tts_models():
    if _WARM_SPEC is not None and _WARM_VOC is not None:
        return _WARM_SPEC, _WARM_VOC
    from nemo.collections.tts.models import FastPitchModel, HifiGanModel

    spec = FastPitchModel.from_pretrained(TTS_SPEC_NAME).eval().cuda()
    vocoder = HifiGanModel.from_pretrained(TTS_VOCODER_NAME).eval().cuda()
    return spec, vocoder


class TtsIn(BaseModel):
    model: str = "rva-tts"
    input: str = ""
    voice: str = "0"
    response_format: str = "pcm"


def _wav_bytes_to_path(raw: bytes) -> str:
    audio, rate = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
    if getattr(audio, "ndim", 1) > 1:
        audio = np.mean(audio, axis=1)
    path = f"/tmp/rva_utt_{uuid.uuid4().hex}.wav"
    sf.write(path, audio, rate)
    return path


def _transcribe_wav(raw: bytes) -> str:
    path = _wav_bytes_to_path(raw)
    text = asr_model().transcribe([path])[0]
    if hasattr(text, "text"):
        text = text.text
    return str(text).strip()


def _synthesize_pcm(text: str, *, voice: str) -> bytes:
    spec, vocoder = tts_models()
    speaker = speaker_id_from_voice(voice)
    parsed = spec.parse(text or "hola")
    with torch.inference_mode():
        spectrogram = spec.generate_spectrogram(tokens=parsed, speaker=speaker)
        audio = vocoder.convert_spectrogram_to_audio(spec=spectrogram)
    wav = audio.to("cpu").detach().numpy().flatten().astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, wav, NEMO_TTS_HZ, format="WAV", subtype="PCM_16")
    pcm_native = _wav_to_pcm_s16le(buf.getvalue(), expected_rate=NEMO_TTS_HZ)
    return resample_pcm16(pcm_native, NEMO_TTS_HZ, OPENAI_PCM_HZ)


def _wav_to_pcm_s16le(raw: bytes, *, expected_rate: int) -> bytes:
    with wave.open(io.BytesIO(raw), "rb") as w:
        if w.getsampwidth() != 2:
            raise HTTPException(status_code=500, detail="unexpected wav width")
        rate = w.getframerate()
        frames = w.readframes(w.getnframes())
    if rate != expected_rate:
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
    if body.response_format != "pcm":
        raise HTTPException(status_code=400, detail="only response_format=pcm is supported")
    pcm = _synthesize_pcm(body.input, voice=body.voice)
    return Response(content=pcm, media_type="application/octet-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
