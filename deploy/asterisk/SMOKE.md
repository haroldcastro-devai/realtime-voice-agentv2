# Softphone / pjsua smoke (manual, not CI)

Fictional **Acme Telco** demo. Run on your machine only. GitHub Actions does **not**
start Asterisk, pjsua, or Docker for this story.

## Prerequisites

1. [deploy/asterisk/README.md](README.md): `docker compose up` (Asterisk on loopback).
2. Agent AudioSocket listener on `0.0.0.0:8090` (see `.env.example` `RVA_AUDIOSOCKET_*`).
3. Optional stub (no full agent yet):

```bash
python scripts/audiosocket_smoke_stub.py
```

The stub accepts one TCP connection and prints each AudioSocket frame until hangup.

## Register and dial

| Setting | Value |
|---------|--------|
| SIP server | `127.0.0.1:5060` (UDP) |
| User | `ava` |
| Password | `rva-demo` (demo only) |
| Dial | **1000** |

Expected path: answer → `Stasis(rva)` → ARI continues to AudioSocket → TCP to
`host.docker.internal:8090` with UUID `aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa`.

Success: the stub logs a UUID frame (and later PCM or hangup). Asterisk logs show
the channel entering Stasis and AudioSocket.

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
- **ARI path stuck:** run the RVA ARI app (later wiring); for smoke, direct dialplan
  continue still reaches AudioSocket once the channel is in `[audiosocket]`.

Out of scope: automating this flow in CI, campaign dialer, measured latency.