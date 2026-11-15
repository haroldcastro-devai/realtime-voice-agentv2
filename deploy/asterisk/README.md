# Local Asterisk (PJSIP + AudioSocket)

Fictional **Acme Telco** / **Ava** demo. Runs on the developer machine. No cloud PBX.

## What you get

| Piece | Value |
|-------|--------|
| SIP | `127.0.0.1:5060` (UDP only) |
| Softphone | user `ava`, password `rva-demo` (demo only) |
| Extension | **1000** answers, then `AudioSocket` to the agent |
| Agent socket | listen `0.0.0.0:8090` (`RVA_AUDIOSOCKET_HOST` / `RVA_AUDIOSOCKET_PORT`) so `host-gateway` can connect |
| From the container | `host.docker.internal:8090` |

ARI, the agent TCP listener, and a pjsua smoke call are later issues (NAT-25, NAT-26).

## Start

From this directory, with Docker Compose:

```bash
docker compose up
```

Keep the agent AudioSocket listener on `0.0.0.0:8090` before dialing **1000**. Binding only `127.0.0.1` is not reachable from the container on Linux. Register a local softphone to `127.0.0.1` as `ava` (SIP stays loopback).

Stop with `docker compose down`.
