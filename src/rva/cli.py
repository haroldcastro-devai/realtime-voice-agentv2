"""``rva`` command-line interface."""

from __future__ import annotations

import argparse
import json
import sys

from rva.agent import AgentRuntime
from rva.ari import AriClient, AriError
from rva.colab import ColabOrchestrator
from rva.dashboard import (
    DashboardError,
    dashboard_token_required,
    dashboard_url,
    serve_dashboard,
)
from rva.dialer import (
    DialerError,
    campaign_csv_from_env,
    load_acme_campaign,
    run_acme_campaign_jobs,
)
from rva.recordings import (
    RecordingArchive,
    minio_bucket_name,
    recording_backend_modes,
    recordings_enabled,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rva", description="Acme Telco / Ava agent tools")
    sub = parser.add_subparsers(dest="command", required=True)
    dialer = sub.add_parser("dialer", help="Fictional Acme campaign dialer (ARI)")
    dialer_sub = dialer.add_subparsers(dest="dialer_cmd", required=True)
    originate = dialer_sub.add_parser(
        "originate",
        help="Originate Stasis calls from the bundled fictional CSV",
    )
    originate.add_argument(
        "--csv",
        type=str,
        default=None,
        help="Campaign CSV (default: deploy/dialer/acme_campaign.csv)",
    )
    originate.set_defaults(handler=_dialer_originate)
    panel = sub.add_parser("dashboard", help="Local loopback status panel")
    panel_sub = panel.add_subparsers(dest="dashboard_cmd", required=True)
    serve = panel_sub.add_parser("serve", help="HTTP panel on 127.0.0.1 (calls, latency, Colab)")
    serve.set_defaults(handler=_dashboard_serve)
    colab = sub.add_parser("colab", help="Colab GPU worker")
    colab_sub = colab.add_subparsers(dest="colab_cmd", required=True)
    status = colab_sub.add_parser("status", help="Health, RTT, backoff, and fallback flags")
    status.set_defaults(handler=_colab_status)
    recordings = sub.add_parser("recordings", help="Optional MinIO/RabbitMQ archive flags")
    rec_sub = recordings.add_subparsers(dest="recordings_cmd", required=True)
    rec_status = rec_sub.add_parser("status", help="Show whether post-call archive is enabled")
    rec_status.set_defaults(handler=_recordings_status)
    agent = sub.add_parser("agent", help="Full agent: ARI + AudioSocket + dashboard")
    agent_sub = agent.add_subparsers(dest="agent_cmd", required=True)
    agent_serve = agent_sub.add_parser(
        "serve",
        help="Loopback dashboard, AudioSocket listener, ARI Stasis",
    )
    agent_serve.set_defaults(handler=_agent_serve)
    args = parser.parse_args(argv)
    return int(args.handler(args))


def _dialer_originate(args: argparse.Namespace) -> int:
    from pathlib import Path

    path = Path(args.csv) if args.csv else campaign_csv_from_env()
    try:
        contacts = load_acme_campaign(path)
        client = AriClient.from_env()
        client.register()
        jobs = run_acme_campaign_jobs(client, contacts)
    except (DialerError, AriError) as exc:
        partial = getattr(exc, "originated", None) or []
        jobs_payload = getattr(exc, "jobs", None) or []
        payload = {
            "error": str(exc),
            "campaign_csv": str(path),
            "jobs": jobs_payload,
            "originated": [
                {
                    "msisdn": row.msisdn,
                    "channel_id": row.channel_id,
                    "endpoint": row.endpoint,
                    "audio_uuid": row.audio_uuid,
                }
                for row in partial
            ],
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1
    payload = {
        "campaign_csv": str(path),
        "jobs": jobs,
        "originated": [row for row in jobs if row.get("state") == "done"],
    }
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _dashboard_serve(_args: argparse.Namespace) -> int:
    try:
        server = serve_dashboard()
    except DashboardError as exc:
        json.dump({"error": str(exc)}, sys.stdout)
        sys.stdout.write("\n")
        return 1
    host, port = server.server_address[:2]
    url = dashboard_url(host, port)
    payload = {"dashboard_url": url, "api": f"{url}api/dashboard"}
    if dashboard_token_required():
        payload["token_required"] = True
        payload["hint"] = "Open with ?token=<RVA_DASHBOARD_TOKEN> or send Authorization: Bearer"
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        from rva.dashboard import shutdown_server

        shutdown_server(server)
    return 0


def _recordings_status(_args: argparse.Namespace) -> int:
    archive = RecordingArchive.shared()
    payload = {
        "enabled": recordings_enabled(),
        "bucket": minio_bucket_name(),
        "archive_active": archive.enabled,
        "backends": recording_backend_modes(),
    }
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _agent_serve(_args: argparse.Namespace) -> int:
    runtime = AgentRuntime()
    try:
        payload = runtime.start()
    except (AriError, DashboardError) as exc:
        json.dump({"error": str(exc)}, sys.stdout)
        sys.stdout.write("\n")
        return 1
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return runtime.run_until_interrupt()


def _colab_status(_args: argparse.Namespace) -> int:
    orch = ColabOrchestrator.shared()
    snap = orch.refresh()
    payload = {
        "configured": snap.configured,
        "health_ok": snap.health_ok,
        "rtt_ms": snap.rtt_ms,
        "consecutive_failures": snap.consecutive_failures,
        "backoff_remaining_s": round(snap.backoff_remaining_s, 3),
        "fallback_stt_tts": snap.fallback_stt_tts,
        "in_call": snap.in_call,
        "pinned_remote": snap.pinned_remote,
    }
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
