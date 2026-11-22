"""Dialer job queue: queued / running / retry / done / failed (stdlib sqlite optional)."""

from __future__ import annotations

import os
import sqlite3
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from rva.ari import AriClient, AriError


class ContactLike(Protocol):
    msisdn: str
    name: str


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY = "retry"
    DONE = "done"
    FAILED = "failed"


_READY = frozenset({JobState.QUEUED, JobState.RETRY})
_ACTIVE = frozenset({JobState.QUEUED, JobState.RETRY, JobState.RUNNING})


class JobStoreError(ValueError):
    """Invalid job transition or store failure."""


@dataclass
class DialerJob:
    job_id: str
    msisdn: str
    state: JobState
    attempts: int = 0
    max_attempts: int = 3
    last_error: str | None = None
    channel_id: str | None = None
    audio_uuid: str | None = None
    endpoint: str | None = None
    name: str = ""


def _env(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None or raw == "" or raw == "CHANGE_ME":
        return None
    return raw


def open_job_store(db_path: Path | None = None) -> DialerJobStore:
    path = db_path if db_path is not None else _db_path_from_env()
    if path is None:
        return InMemoryDialerStore()
    return SqliteDialerStore(path)


def _db_path_from_env() -> Path | None:
    raw = _env("RVA_DIALER_DB")
    if raw is None:
        return None
    return Path(raw)


class DialerJobStore:
    def enqueue_contacts(
        self, contacts: Sequence[ContactLike], *, max_attempts: int
    ) -> list[DialerJob]:
        raise NotImplementedError

    def prepare_campaign(
        self, contacts: Sequence[ContactLike], *, max_attempts: int
    ) -> list[DialerJob]:
        return self.enqueue_contacts(contacts, max_attempts=max_attempts)

    def list_jobs(self) -> list[DialerJob]:
        raise NotImplementedError

    def get(self, job_id: str) -> DialerJob:
        raise NotImplementedError

    def ready_jobs(self) -> list[DialerJob]:
        return [job for job in self.list_jobs() if job.state in _READY]

    def mark_running(self, job_id: str) -> DialerJob:
        job = self.get(job_id)
        if job.state not in _READY:
            raise JobStoreError(f"job {job_id} not ready (state={job.state})")
        return self._save(job, state=JobState.RUNNING, attempts=job.attempts + 1)

    def mark_done(
        self, job_id: str, *, channel_id: str, audio_uuid: str, endpoint: str
    ) -> DialerJob:
        job = self.get(job_id)
        if job.state != JobState.RUNNING:
            raise JobStoreError(f"job {job_id} not running")
        return self._save(
            job,
            state=JobState.DONE,
            channel_id=channel_id,
            audio_uuid=audio_uuid,
            endpoint=endpoint,
            last_error=None,
        )

    def mark_failure(self, job_id: str, error: str) -> DialerJob:
        job = self.get(job_id)
        if job.state != JobState.RUNNING:
            raise JobStoreError(f"job {job_id} not running")
        if job.attempts < job.max_attempts:
            return self._save(job, state=JobState.RETRY, last_error=error)
        return self._save(job, state=JobState.FAILED, last_error=error)

    def _save(self, job: DialerJob, **changes: object) -> DialerJob:
        raise NotImplementedError


class InMemoryDialerStore(DialerJobStore):
    def __init__(self) -> None:
        self._jobs: dict[str, DialerJob] = {}

    def enqueue_contacts(
        self, contacts: Sequence[ContactLike], *, max_attempts: int
    ) -> list[DialerJob]:
        created: list[DialerJob] = []
        for contact in contacts:
            job_id = uuid.uuid4().hex
            job = DialerJob(
                job_id=job_id,
                msisdn=contact.msisdn,
                name=contact.name,
                state=JobState.QUEUED,
                max_attempts=max_attempts,
            )
            self._jobs[job_id] = job
            created.append(job)
        return created

    def list_jobs(self) -> list[DialerJob]:
        return list(self._jobs.values())

    def get(self, job_id: str) -> DialerJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobStoreError(f"unknown job {job_id}")
        return job

    def _save(self, job: DialerJob, **changes: object) -> DialerJob:
        updated = DialerJob(
            job_id=job.job_id,
            msisdn=job.msisdn,
            name=job.name,
            state=changes.get("state", job.state),  # type: ignore[arg-type]
            attempts=changes.get("attempts", job.attempts),  # type: ignore[arg-type]
            max_attempts=job.max_attempts,
            last_error=changes.get("last_error", job.last_error),  # type: ignore[arg-type]
            channel_id=changes.get("channel_id", job.channel_id),  # type: ignore[arg-type]
            audio_uuid=changes.get("audio_uuid", job.audio_uuid),  # type: ignore[arg-type]
            endpoint=changes.get("endpoint", job.endpoint),  # type: ignore[arg-type]
        )
        self._jobs[job.job_id] = updated
        return updated


_SCHEMA = """
CREATE TABLE IF NOT EXISTS dialer_jobs (
    job_id TEXT PRIMARY KEY,
    msisdn TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL,
    last_error TEXT,
    channel_id TEXT,
    audio_uuid TEXT,
    endpoint TEXT
);
"""


class SqliteDialerStore(DialerJobStore):
    _SELECT = """
        SELECT job_id, msisdn, name, state, attempts, max_attempts,
               last_error, channel_id, audio_uuid, endpoint
        FROM dialer_jobs
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
        self.reconcile_stale_running()

    def reconcile_stale_running(self) -> None:
        for job in self.list_jobs():
            if job.state == JobState.RUNNING:
                self._save(
                    job,
                    state=JobState.RETRY,
                    last_error=job.last_error or "interrupted while running",
                )

    def prepare_campaign(
        self, contacts: Sequence[ContactLike], *, max_attempts: int
    ) -> list[DialerJob]:
        active = {job.msisdn: job for job in self.list_jobs() if job.state in _ACTIVE}
        created: list[DialerJob] = []
        for contact in contacts:
            if contact.msisdn in active:
                continue
            created.extend(self.enqueue_contacts([contact], max_attempts=max_attempts))
        return created

    def enqueue_contacts(
        self, contacts: Sequence[ContactLike], *, max_attempts: int
    ) -> list[DialerJob]:
        created: list[DialerJob] = []
        with self._connect() as conn:
            for contact in contacts:
                job_id = uuid.uuid4().hex
                job = DialerJob(
                    job_id=job_id,
                    msisdn=contact.msisdn,
                    name=contact.name,
                    state=JobState.QUEUED,
                    max_attempts=max_attempts,
                )
                conn.execute(
                    """
                    INSERT INTO dialer_jobs (
                        job_id, msisdn, name, state, attempts, max_attempts
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job.job_id,
                        job.msisdn,
                        job.name,
                        job.state,
                        job.attempts,
                        job.max_attempts,
                    ),
                )
                created.append(job)
            conn.commit()
        return created

    def list_jobs(self) -> list[DialerJob]:
        with self._connect() as conn:
            rows = conn.execute(f"{self._SELECT} ORDER BY job_id").fetchall()
        return [_row_to_job(row) for row in rows]

    def get(self, job_id: str) -> DialerJob:
        with self._connect() as conn:
            row = conn.execute(f"{self._SELECT} WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise JobStoreError(f"unknown job {job_id}")
        return _row_to_job(row)

    def _save(self, job: DialerJob, **changes: object) -> DialerJob:
        updated = DialerJob(
            job_id=job.job_id,
            msisdn=job.msisdn,
            name=job.name,
            state=changes.get("state", job.state),  # type: ignore[arg-type]
            attempts=changes.get("attempts", job.attempts),  # type: ignore[arg-type]
            max_attempts=job.max_attempts,
            last_error=changes.get("last_error", job.last_error),  # type: ignore[arg-type]
            channel_id=changes.get("channel_id", job.channel_id),  # type: ignore[arg-type]
            audio_uuid=changes.get("audio_uuid", job.audio_uuid),  # type: ignore[arg-type]
            endpoint=changes.get("endpoint", job.endpoint),  # type: ignore[arg-type]
        )
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE dialer_jobs SET
                    state = ?, attempts = ?, last_error = ?,
                    channel_id = ?, audio_uuid = ?, endpoint = ?
                WHERE job_id = ?
                """,
                (
                    updated.state,
                    updated.attempts,
                    updated.last_error,
                    updated.channel_id,
                    updated.audio_uuid,
                    updated.endpoint,
                    updated.job_id,
                ),
            )
            conn.commit()
        return updated

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn


def _row_to_job(row: sqlite3.Row) -> DialerJob:
    return DialerJob(
        job_id=str(row["job_id"]),
        msisdn=str(row["msisdn"]),
        name=str(row["name"]),
        state=JobState(str(row["state"])),
        attempts=int(row["attempts"]),
        max_attempts=int(row["max_attempts"]),
        last_error=str(row["last_error"]) if row["last_error"] is not None else None,
        channel_id=str(row["channel_id"]) if row["channel_id"] is not None else None,
        audio_uuid=str(row["audio_uuid"]) if row["audio_uuid"] is not None else None,
        endpoint=str(row["endpoint"]) if row["endpoint"] is not None else None,
    )


def run_campaign_jobs(client: AriClient, store: DialerJobStore) -> list[DialerJob]:
    """Process every job that is ``queued`` or ``retry`` until none remain."""
    from rva.dialer import DialerError, build_endpoint

    while store.ready_jobs():
        for job in list(store.ready_jobs()):
            running = store.mark_running(job.job_id)
            try:
                endpoint = build_endpoint(running.msisdn)
            except DialerError as exc:
                store.mark_failure(running.job_id, str(exc))
                continue
            audio_uuid = str(uuid.uuid4())
            try:
                channel_id = client.originate_channel(endpoint, [audio_uuid])
            except AriError as exc:
                store.mark_failure(running.job_id, str(exc))
                continue
            store.mark_done(
                running.job_id,
                channel_id=channel_id,
                audio_uuid=audio_uuid,
                endpoint=endpoint,
            )
    return store.list_jobs()


def job_to_dict(job: DialerJob) -> dict[str, object]:
    return {
        "job_id": job.job_id,
        "msisdn": job.msisdn,
        "name": job.name,
        "state": job.state.value,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "last_error": job.last_error,
        "channel_id": job.channel_id,
        "audio_uuid": job.audio_uuid,
        "endpoint": job.endpoint,
    }
