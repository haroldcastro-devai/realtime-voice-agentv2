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

Nothing else is implemented yet. Latency numbers will appear only after
measured runs (see later issues).

## Setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
ruff check src tests
```

## Roadmap

Local Asterisk (Docker), AudioSocket, VAD/session, pipeline backends, Colab
NeMo worker, dialer, dashboard, and measured benchmarks. Tracked in Jira
project NAT.

## License

MIT. Copyright (c) 2026 Harold Castro.
