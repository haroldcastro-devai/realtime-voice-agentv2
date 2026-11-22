# Colab NeMo worker (Spanish STT/TTS)

Fictional **Acme Telco** demo. GPU inference runs in [Google Colab](https://colab.research.google.com);
the local agent stays CPU-only and calls HTTP with `RVA_COLAB_URL` + `RVA_COLAB_TOKEN`
(see `.env.example`).

## Notebook

Open [`notebooks/colab_nemo_es.ipynb`](../notebooks/colab_nemo_es.ipynb) in Colab with a **T4 GPU**.

The notebook:

1. Installs public NeMo ASR/TTS wheels (Spanish FastPitch + HiFiGAN via `from_pretrained`).
2. Generates a random **Bearer** token and prints an **HTTPS** base URL (optional ngrok; full tunnel
   options are a later docs issue).
3. Starts `colab/nemo_server.py` (OpenAI-compatible `/v1/audio/transcriptions` and
   `/v1/audio/speech`).

## Colab terms

- No JavaScript or background loops to bypass idle disconnects.
- Keep the notebook tab open while you demo; respect [Colab usage limits](https://research.google.com/colaboratory/faq.html).

## Local wiring (later orchestrator issues)

Point `RVA_STT_URL` and `RVA_TTS_URL` at the printed HTTPS base URL, set
`RVA_STT_TOKEN` / `RVA_TTS_TOKEN` to the Bearer value, and use `http` backends in pytest locally
with mocks.