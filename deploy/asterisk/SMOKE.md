# Softphone / pjsua smoke (manual, not CI)

Fictional **Acme Telco** demo. Run on your machine only. GitHub Actions does **not**
start Asterisk, pjsua, or Docker for this story.

## Prerequisites

1. [deploy/asterisk/README.md](README.md): `docker compose up` (Asterisk on loopback).
2. **Full agent** on the host (ARI + AudioSocket + dashboard in one process):

```bash
rva agent serve
```

Set `RVA_ARI_*`, `RVA_AUDIOSOCKET_*` (bind `0.0.0.0:8090`), and optional
`RVA_DASHBOARD_*` from `.env.example`. On `StasisStart`, the app `continue`s the
channel into `[audiosocket]` (see `src/rva/ari.py`).
3. Optional frame-only stub (no pipeline):

```bash
python scripts/audiosocket_smoke_stub.py
```

The stub binds IPv4 only (`0.0.0.0` or `127.0.0.1`), accepts one TCP connection, and
prints each AudioSocket frame until hangup.

## Register and dial

| Setting | Value |
|---------|--------|
| SIP server | `127.0.0.1:5060` (UDP) |
| User | `ava` |
| Password | `rva-demo` (demo only) |
| Dial | **1000** |

Expected path (matches `deploy/asterisk/etc/extensions.conf`):

1. Inbound **1000** → `Stasis(rva,aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa)` (no `Answer()` yet).
2. ARI `StasisStart` → RVA app calls **continue** into `[audiosocket]` extension `s`.
3. `[audiosocket]` → `Answer()` → `AudioSocket(...,host.docker.internal:8090)` → TCP to
   your listener with UUID `aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa`.

Success: the stub logs a UUID frame (and later PCM or hangup). Asterisk logs show Stasis,
then AudioSocket.

## pjsua (CLI)

Install [PJSIP](https://www.pjsip.org/) / pjsua on your OS. From any directory:

```bash
pjsua --null-audio --auto-answer=200 \
  --id sip:ava@127.0.0.1 \
  --registrar sip:127.0.0.1 \
  --realm "*" \
  --username ava \
  --password rva-demo \
  sip:1000@127.0.0.1
```

Hang up with `q` when finished. No cloud registrar, no public IP.

## GUI softphone (optional)

Any local softphone (Linphone, MicroSIP, Zoiper, etc.):

1. Account: SIP UDP, domain `127.0.0.1`, user `ava`, password `rva-demo`.
2. Disable STUN / ICE if the client defaults to public discovery.
3. Call extension **1000**.

## Troubleshooting

- **No AudioSocket on the stub:** agent not listening on `0.0.0.0:8090`, or Asterisk
  container cannot reach the host (`host.docker.internal` / `host-gateway`).
- **Registration fails:** confirm `127.0.0.1:5060/udp` and credentials match
  `deploy/asterisk/etc/pjsip.conf`.
- **Stuck in Stasis / no AudioSocket:** confirm the ARI app is registered (`RVA_ARI_APP=rva`)
  and that `continue` targets context `audiosocket` extension `s` (see `tests/test_ari.py`).
- **401 on ARI:** use demo user `rva` / `rva-ari-demo` from `deploy/asterisk/etc/ari.conf`.

Out of scope: automating this flow in CI, campaign dialer, measured latency.
