"""``rva`` command-line interface."""

from __future__ import annotations

import argparse
import json
import sys

from rva.ari import AriClient, AriError
from rva.colab import ColabOrchestrator
from rva.dialer import (
    DialerError,
    campaign_csv_from_env,
    load_acme_campaign,
    run_acme_campaign_jobs,
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
    colab = sub.add_parser("colab", help="Colab GPU worker")
    colab_sub = colab.add_subparsers(dest="colab_cmd", required=True)
    status = colab_sub.add_parser("status", help="Health, RTT, backoff, and fallback flags")
    status.set_defaults(handler=_colab_status)
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
