# Colab NeMo worker (Spanish STT/TTS)

Fictional **Acme Telco** demo. GPU inference runs in [Google Colab](https://colab.research.google.com);
the local agent stays CPU-only and calls HTTP with `RVA_COLAB_URL` + `RVA_COLAB_TOKEN`
(see `.env.example`).

## Notebook

Open [`notebooks/colab_nemo_es.ipynb`](../notebooks/colab_nemo_es.ipynb) in Colab with a **T4 GPU**.

Before this repo lands on `main`, set Colab secret or env `RVA_GIT_BRANCH` to your feature
branch (for example `feat/NAT-27-colab-nemo-es`) so `git clone -b` picks up `colab/nemo_server.py`.

TTS uses public checkpoints `tts_es_fastpitch_multispeaker` and
`tts_es_hifigan_ft_fastpitch_multispeaker`. Pass OpenAI `voice` as a speaker id **0–173** (default `0`).

The notebook:

1. Installs public NeMo ASR/TTS wheels (Spanish FastPitch + HiFiGAN via `from_pretrained`).
2. Generates a random **Bearer** token and prints an **HTTPS** base URL (optional ngrok; full tunnel
   options are a later docs issue).
3. Starts `colab/nemo_server.py` (OpenAI-compatible `/v1/audio/transcriptions` and
   `/v1/audio/speech`).

## Colab terms

- No JavaScript or background loops to bypass idle disconnects.
- Keep the notebook tab open while you demo; respect [Colab usage limits](https://research.google.com/colaboratory/faq.html).

## Local wiring

Point `RVA_STT_URL` and `RVA_TTS_URL` at the printed HTTPS base URL, set
`RVA_STT_TOKEN` / `RVA_TTS_TOKEN` to the Bearer value, and set `RVA_COLAB_URL` /
`RVA_COLAB_TOKEN` for health checks. Use `rva colab status` to read health, RTT,
backoff, and STT/TTS fallback flags (`rva.colab` keeps HTTP pinned during an active call).