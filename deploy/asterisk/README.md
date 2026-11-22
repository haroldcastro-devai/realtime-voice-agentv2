# Local Asterisk (PJSIP + AudioSocket)

Fictional **Acme Telco** / **Ava** demo. Runs on the developer machine. No cloud PBX.

## What you get

| Piece | Value |
|-------|--------|
| SIP | `127.0.0.1:5060` (UDP only) |
| Softphone | user `ava`, password `rva-demo` (demo only) |
| Extension | **1000** enters `Stasis(rva)`, then `[audiosocket]` `AudioSocket` |
| ARI | `127.0.0.1:8088` user `rva` / `rva-ari-demo` (demo only) |
| Agent socket | listen `0.0.0.0:8090` (`RVA_AUDIOSOCKET_HOST` / `RVA_AUDIOSOCKET_PORT`) so `host-gateway` can connect |
| From the container | `host.docker.internal:8090` |

The agent TCP listener and a pjsua smoke call are later issues (NAT-26).

## Start

From this directory, with Docker Compose:

```bash
docker compose up
```

Keep the agent AudioSocket listener on `0.0.0.0:8090` before dialing **1000**. Binding only `127.0.0.1` is not reachable from the container on Linux. Register a local softphone to `127.0.0.1` as `ava` (SIP stays loopback).

ARI: set `RVA_ARI_*` from `.env.example`. `AriClient.register()` checks `/ari/asterisk/info`; `AriApp.handle_event` starts a `CallSession` on `StasisStart` and continues the channel into `[audiosocket]`.

Stop with `docker compose down`.
