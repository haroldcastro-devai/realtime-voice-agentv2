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
- AudioSocket framing (`rva.audiosocket`) and band-limited resample (`rva.resample`)

Call-handling, telephony, and measured latency numbers are still later issues.

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

## Roadmap

Local Asterisk (Docker), AudioSocket, VAD/session, pipeline backends, Colab
NeMo worker, dialer, dashboard, and measured benchmarks. Tracked in Jira
project NAT.

## License

MIT. Copyright (c) 2026 Harold Castro.
