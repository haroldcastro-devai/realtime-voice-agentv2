"""Dialer job state machine and bounded retries."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from rva.ari import AriClient, AriError
from rva.dialer import CampaignContact, DialerError, max_attempts_from_env
from rva.dialer_jobs import (
    InMemoryDialerStore,
    JobState,
    JobStoreError,
    SqliteDialerStore,
    run_campaign_jobs,
)

_LOOP = "127.0.0.1"


def test_job_state_transitions_on_success() -> None:
    store = InMemoryDialerStore()
    store.enqueue_contacts([CampaignContact("+573000000001")], max_attempts=2)

    class OkClient:
        def originate_channel(self, endpoint: str, app_args: list[str]) -> str:
            return "chan-1"

    jobs = run_campaign_jobs(OkClient(), store)  # type: ignore[arg-type]
    assert len(jobs) == 1
    job = jobs[0]
    assert job.state == JobState.DONE
    assert job.attempts == 1
    assert job.channel_id == "chan-1"


def test_job_retries_then_fails() -> None:
    store = InMemoryDialerStore()
    store.enqueue_contacts([CampaignContact("+573000000001")], max_attempts=2)

    class FailClient:
        def originate_channel(self, endpoint: str, app_args: list[str]) -> str:
            raise AriError("HTTP 500")

    jobs = run_campaign_jobs(FailClient(), store)  # type: ignore[arg-type]
    assert jobs[0].state == JobState.FAILED
    assert jobs[0].attempts == 2
    assert jobs[0].last_error is not None


def test_retry_succeeds_on_second_attempt() -> None:
    store = InMemoryDialerStore()
    store.enqueue_contacts([CampaignContact("+573000000001")], max_attempts=3)
    calls = {"n": 0}

    class FlakyClient:
        def originate_channel(self, endpoint: str, app_args: list[str]) -> str:
            calls["n"] += 1
            if calls["n"] == 1:
                raise AriError("first try failed")
            return "chan-ok"

    jobs = run_campaign_jobs(FlakyClient(), store)  # type: ignore[arg-type]
    assert jobs[0].state == JobState.DONE
    assert jobs[0].attempts == 2


def test_mark_running_rejects_terminal_state() -> None:
    store = InMemoryDialerStore()
    created = store.enqueue_contacts([CampaignContact("+573000000001")], max_attempts=1)
    running = store.mark_running(created[0].job_id)
    store.mark_failure(running.job_id, "originate failed")
    assert store.get(created[0].job_id).state == JobState.FAILED
    with pytest.raises(JobStoreError):
        store.mark_running(created[0].job_id)


def test_sqlite_store_persists_states(tmp_path: Path) -> None:
    db = tmp_path / "jobs.db"
    sqlite = SqliteDialerStore(db)
    sqlite.enqueue_contacts(
        [CampaignContact("+573000000001"), CampaignContact("+573000000002")],
        max_attempts=2,
    )
    again = SqliteDialerStore(db)
    jobs = again.list_jobs()
    assert len(jobs) == 2
    assert all(j.state == JobState.QUEUED for j in jobs)


class _Store:
    def __init__(self) -> None:
        self.posts: list[str] = []


def _flaky_server(
    store: _Store, fail_msisdns: set[str], attempts: dict[str, int]
) -> ThreadingHTTPServer:
    channel = iter(["c1", "c2", "c3", "c4"])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _fmt: str, *_args: object) -> None:
            return

        def do_POST(self) -> None:
            store.posts.append(self.path)
            path = self.path.split("?", 1)[0]
            if path == "/ari/channels":
                from urllib.parse import parse_qs, urlparse

                qs = parse_qs(urlparse(self.path).query)
                endpoint = qs.get("endpoint", [""])[0]
                msisdn_key = endpoint.split("/")[1].split("@")[0] if "@" in endpoint else ""
                attempts[msisdn_key] = attempts.get(msisdn_key, 0) + 1
                if msisdn_key in fail_msisdns and attempts[msisdn_key] < 2:
                    self.send_response(500)
                    self.end_headers()
                    return
                body = json.dumps({"id": next(channel, "cz"), "state": "Down"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

    return ThreadingHTTPServer((_LOOP, 0), Handler)


def test_http_campaign_jobs_cover_retry_transitions() -> None:
    contacts = [
        CampaignContact("+573000000001"),
        CampaignContact("+573000000002"),
    ]
    store = InMemoryDialerStore()
    store.enqueue_contacts(contacts, max_attempts=3)
    http_store = _Store()
    attempt_counts: dict[str, int] = {}
    server = _flaky_server(http_store, fail_msisdns={"573000000001"}, attempts=attempt_counts)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        client = AriClient(f"http://{_LOOP}:{port}", "rva", "rva-ari-demo")
        jobs = run_campaign_jobs(client, store)
        by_msisdn = {j.msisdn: j for j in jobs}
        assert by_msisdn["+573000000001"].state == JobState.DONE
        assert by_msisdn["+573000000002"].state == JobState.DONE
        assert attempt_counts.get("573000000001", 0) >= 2
    finally:
        server.shutdown()
        server.server_close()


def test_sqlite_prepare_campaign_skips_duplicate_msisdn(tmp_path: Path) -> None:
    db = tmp_path / "jobs.db"
    contacts = [CampaignContact("+573000000001"), CampaignContact("+573000000002")]
    store = SqliteDialerStore(db)
    store.prepare_campaign(contacts, max_attempts=2)
    again = SqliteDialerStore(db)
    created = again.prepare_campaign(contacts, max_attempts=2)
    assert created == []
    assert len(again.list_jobs()) == 2


def test_sqlite_persists_done_state(tmp_path: Path) -> None:
    db = tmp_path / "jobs.db"
    store = SqliteDialerStore(db)
    store.prepare_campaign([CampaignContact("+573000000001")], max_attempts=2)

    class OkClient:
        def originate_channel(self, endpoint: str, app_args: list[str]) -> str:
            return "ch-sqlite"

    run_campaign_jobs(OkClient(), store)  # type: ignore[arg-type]
    reloaded = SqliteDialerStore(db)
    job = reloaded.list_jobs()[0]
    assert job.state == JobState.DONE
    assert job.channel_id == "ch-sqlite"


def test_endpoint_template_failure_does_not_stick_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RVA_DIALER_ENDPOINT", "Local/{typo}@acme-campaign")
    store = InMemoryDialerStore()
    store.prepare_campaign([CampaignContact("+573000000001")], max_attempts=2)

    class Noop:
        def originate_channel(self, endpoint: str, app_args: list[str]) -> str:
            raise AssertionError("originate should not run")

    jobs = run_campaign_jobs(Noop(), store)  # type: ignore[arg-type]
    assert jobs[0].state == JobState.FAILED
    assert store.ready_jobs() == []


def test_ari_timeout_error_retries_then_fails() -> None:
    store = InMemoryDialerStore()
    store.prepare_campaign([CampaignContact("+573000000001")], max_attempts=2)

    class TimeoutClient:
        def originate_channel(self, endpoint: str, app_args: list[str]) -> str:
            raise AriError("timeout")

    jobs = run_campaign_jobs(TimeoutClient(), store)  # type: ignore[arg-type]
    assert jobs[0].state == JobState.FAILED
    assert jobs[0].last_error is not None
    assert "timeout" in jobs[0].last_error


def test_max_attempts_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RVA_DIALER_MAX_RETRIES", "5")
    assert max_attempts_from_env() == 5
    monkeypatch.setenv("RVA_DIALER_MAX_RETRIES", "0")
    with pytest.raises(DialerError):
        max_attempts_from_env()
