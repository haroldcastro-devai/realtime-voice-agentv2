# realtime-voice-agentv2

MIT portfolio project by **Harold Castro**. A local realtime voice agent for
phone calls (STT → LLM → TTS, barge-in, campaign dialer, latency panel).

Demo scenario is fictional: **Acme Telco** and agent **Ava**. Contact numbers
use the `+57 300 000 0001` range. Configuration uses the `RVA_*` prefix
(see `.env.example`). This repository contains no employer, carrier, or
customer data.

## Implemented

- Python 3.10+ package layout (`src/rva`)
- MIT license
- Local `pytest` and `ruff` via the `dev` extra
- GitHub Actions (`ci`): pytest, ruff, and `scripts/check_clean.py` on Python 3.10 and 3.12
- [CONTRIBUTING.md](CONTRIBUTING.md): branch/PR/review rules and comment signatures
- AudioSocket framing (`rva.audiosocket`), band-limited resample (`rva.resample`), energy VAD (`rva.vad`)
- Call session barge-in (`rva.session`): counted only while the agent is playing TTS; leftover inbound after playback ends is listen, not barge-in
- 20 ms AudioSocket TX pacing (`rva.tx`): deadline spacing; tests use a fake clock and fake socket
- Session fake-socket tests: barge-in, hangup, and 20 ms pacing without Asterisk (`CallSession.play_on`)
- STT/LLM/TTS protocols, mocks, and factory (`rva.pipeline`): one mocked turn in pytest with no network
- OpenAI-compatible HTTP STT/LLM/TTS (`rva.http_backends`): mapping tests use a local fake server
- Per-stage p50/p95 (`rva.metrics`): in-memory STT/LLM/TTS/total samples; `GET /metrics` on loopback JSON (no transcripts)
- Sentence TTS prefetch (`rva.prefetch`): synthesize sentence N+1 while N plays; heard order is unchanged
- Local Asterisk in Docker (`deploy/asterisk`): PJSIP on `127.0.0.1:5060`, extension **1000** → Stasis(`rva`) then AudioSocket; no cloud PBX
- ARI hook (`rva.ari`): app `rva` registers over HTTP; `StasisStart` starts a `CallSession` (fake ARI server in tests)
- Softphone / pjsua smoke ([deploy/asterisk/SMOKE.md](deploy/asterisk/SMOKE.md)): manual steps and `scripts/audiosocket_smoke_stub.py`; not run in CI
- Colab NeMo Spanish worker ([colab/README.md](colab/README.md), [notebooks/colab_nemo_es.ipynb](notebooks/colab_nemo_es.ipynb)): GPU STT/TTS, Bearer + HTTPS URL printed in notebook; not run in CI
- Colab orchestrator (`rva.colab`): probe `/health`, RTT, exponential backoff, `rva colab status`; HTTP STT/TTS fall back to mocks without unpinning an active call
- HTTPS tunnel how-to ([colab/TUNNEL.md](colab/TUNNEL.md)): ngrok and Cloudflare; tunnel secrets stay in Colab Secrets / local `.env` only
- Fictional Acme campaign dialer (`rva.dialer`): bundled CSV in `deploy/dialer/acme_campaign.csv`, `+57300000XXXX` only; `rva dialer originate` POSTs ARI `/ari/channels` (fake HTTP in tests)
- Dialer job states (`rva.dialer_jobs`): `queued` / `running` / `retry` / `done` / `failed`, bounded `RVA_DIALER_MAX_RETRIES`, in-memory or optional sqlite `RVA_DIALER_DB`
- Local dashboard (`rva.dashboard`): `rva dashboard serve` on `RVA_DASHBOARD_HOST` / `RVA_DASHBOARD_PORT` — active calls, p50/p95, Colab UP/DOWN+RTT, optional live transcript (`RVA_DASHBOARD_TRANSCRIPT=1` via `Pipeline.turn` in the same process; ARI/AudioSocket do not call the pipeline until the full listener lands); transcript lines are global, not per channel; optional loopback token `RVA_DASHBOARD_TOKEN` (open the panel as `/?token=…` — the CLI does not print the secret; query tokens may remain in browser history); set `RVA_RECORD_LATENCY=1` so pipeline samples share the same metrics store in-process
- Optional post-call recordings (`rva.recordings`): off unless `RVA_RECORDINGS_ENABLE=1`; PCM lands in fictional bucket `acme-ava-recordings-fictional` (override `RVA_MINIO_BUCKET`); loopback `RVA_MINIO_ENDPOINT` / `RVA_RABBITMQ_URL` or in-memory doubles; buffer via `CALL_BUFFER` (AudioSocket hook pending); `rva recordings status`

The full agent TCP listener is a later issue.

## Setup

Unix/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check src tests scripts
ruff format --check src tests scripts
python scripts/check_clean.py
```

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
ruff check src tests scripts
ruff format --check src tests scripts
python scripts/check_clean.py
```

## Local Asterisk

See [deploy/asterisk/README.md](deploy/asterisk/README.md) and [SMOKE.md](deploy/asterisk/SMOKE.md).
From `deploy/asterisk`: `docker compose up`, then follow the smoke doc (pjsua or a
GUI softphone, extension **1000**, listener on `0.0.0.0:8090`).

## Benchmarks

Mock or HTTP backends (via ``RVA_*_BACKEND``). The bench does not use
``ColabOrchestrator`` fallback/backoff; point HTTP backends at your Colab or mock worker
URLs in ``.env``.

```bash
python scripts/bench_latency.py -n 32
python scripts/bench_latency.py -n 32 --json
python scripts/publish_measured_readme.py --write
python scripts/publish_measured_readme.py --check
```

<!-- measured-latency-start -->

## Measured latency (mock)

Source: [`docs/measured_latency.json`](docs/measured_latency.json) (32 turns, mock backends). Platform, processor, and dependency versions live in that JSON only — not in the table below. Regenerate after re-benchmarking (percentiles may differ by machine; CI checks README↔JSON sync via ``--check``):

```bash
python scripts/publish_measured_readme.py --write
```

| Stage | n | p50 (ms) | p95 (ms) |
| --- | ---: | ---: | ---: |
| stt | 32 | 0.000 | 0.001 |
| llm | 32 | 0.001 | 0.002 |
| tts | 32 | 0.001 | 0.002 |
| total | 32 | 0.001 | 0.005 |

Short portfolio demo narration: [docs/DEMO_VIDEO_SCRIPT.md](docs/DEMO_VIDEO_SCRIPT.md).

<!-- measured-latency-end -->

## Roadmap

Epics E0–E8 are implemented in-tree; see Jira project NAT for optional follow-ups.

## License

MIT. Copyright (c) 2026 Harold Castro.
