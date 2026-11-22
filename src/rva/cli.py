"""``rva`` command-line interface."""

from __future__ import annotations

import argparse
import json
import sys

from rva.colab import ColabOrchestrator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rva", description="Acme Telco / Ava agent tools")
    sub = parser.add_subparsers(dest="command", required=True)
    colab = sub.add_parser("colab", help="Colab GPU worker")
    colab_sub = colab.add_subparsers(dest="colab_cmd", required=True)
    status = colab_sub.add_parser("status", help="Health, RTT, backoff, and fallback flags")
    status.set_defaults(handler=_colab_status)
    args = parser.parse_args(argv)
    return int(args.handler(args))


def _colab_status(_args: argparse.Namespace) -> int:
    orch = ColabOrchestrator()
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
