# Demo video script (≈60 s)

Fictional **Acme Telco** / agent **Ava**. Record screen + voice; no real customer data.

1. **Hook (5 s)** — "This is Ava, a local realtime voice agent: STT, LLM, and TTS on a phone call."
2. **Bench (15 s)** — Terminal: `python scripts/bench_latency.py -n 32`. Point at mock p50/p95 lines; say numbers come from the run, not estimates.
3. **Dashboard (15 s)** — `rva dashboard serve` (optional token). Browser: active calls, latency, Colab status, transcript with safe text rendering.
4. **Telephony skim (15 s)** — `deploy/asterisk` compose up; softphone to extension **1000** or show SMOKE.md steps (cut if no live call).
5. **Close (10 s)** — "MIT portfolio; Jira NAT backlog; Colab GPU path is optional for Spanish STT/TTS."

Re-run `python scripts/publish_measured_readme.py --write` before filming if you change benchmarks.