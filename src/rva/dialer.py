"""Fictional Acme Telco campaign dialer (ARI originate, stdlib only)."""

from __future__ import annotations

import csv
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from rva.ari import AriClient
from rva.dialer_jobs import (
    InMemoryDialerStore,
    JobState,
    job_to_dict,
    open_job_store,
    run_campaign_jobs,
)

_FICTIONAL_MSISDN = re.compile(r"^\+57300000\d{4}$")
_DEFAULT_ENDPOINT = "Local/{digits}@acme-campaign"
_CAMPAIGN_REL = Path("deploy") / "dialer" / "acme_campaign.csv"


class DialerError(ValueError):
    """Campaign CSV or originate failed."""

    def __init__(self, message: str, *, originated: list[OriginateResult] | None = None) -> None:
        super().__init__(message)
        self.originated = list(originated or [])


@dataclass(frozen=True)
class CampaignContact:
    msisdn: str
    name: str = ""


@dataclass(frozen=True)
class OriginateResult:
    msisdn: str
    channel_id: str
    endpoint: str
    audio_uuid: str


def normalize_msisdn(raw: str) -> str:
    stripped = raw.strip()
    if not stripped:
        raise DialerError("empty msisdn")
    compact = re.sub(r"[\s\-()]", "", stripped)
    if compact.startswith("00"):
        compact = "+" + compact[2:]
    if not compact.startswith("+"):
        raise DialerError(f"msisdn must be E.164 with leading +: {raw!r}")
    if not compact[1:].isdigit():
        raise DialerError(f"msisdn must be digits after +: {raw!r}")
    return compact


def is_fictional_acme_msisdn(msisdn: str) -> bool:
    return _FICTIONAL_MSISDN.fullmatch(msisdn) is not None


def load_acme_campaign(path: Path) -> list[CampaignContact]:
    if not path.is_file():
        raise DialerError(f"campaign CSV not found: {path}")
    contacts: list[CampaignContact] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "msisdn" not in reader.fieldnames:
            raise DialerError("campaign CSV must include an msisdn column")
        for row in reader:
            raw = (row.get("msisdn") or "").strip()
            if not raw or raw.startswith("#"):
                continue
            msisdn = normalize_msisdn(raw)
            if not is_fictional_acme_msisdn(msisdn):
                raise DialerError(
                    f"refusing non-fictional msisdn {msisdn!r}; Acme demo only allows +57300000XXXX"
                )
            name = (row.get("name") or "").strip()
            contacts.append(CampaignContact(msisdn=msisdn, name=name))
    if not contacts:
        raise DialerError("campaign CSV has no dialable rows")
    return contacts


def resolve_campaign_csv() -> Path:
    raw = _env("RVA_DIALER_CSV")
    if raw:
        return Path(raw)
    for base in (Path.cwd(), *Path.cwd().parents):
        candidate = base / _CAMPAIGN_REL
        if candidate.is_file():
            return candidate
    packaged = Path(__file__).resolve().parents[2] / _CAMPAIGN_REL
    if packaged.is_file():
        return packaged
    raise DialerError("cannot find deploy/dialer/acme_campaign.csv; set RVA_DIALER_CSV")


def default_campaign_csv() -> Path:
    return resolve_campaign_csv()


def campaign_csv_from_env() -> Path:
    return resolve_campaign_csv()


def _env(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None or raw == "" or raw == "CHANGE_ME":
        return None
    return raw


def max_attempts_from_env() -> int:
    raw = _env("RVA_DIALER_MAX_RETRIES")
    if raw is None:
        return 3
    try:
        value = int(raw)
    except ValueError as exc:
        raise DialerError("RVA_DIALER_MAX_RETRIES must be an integer") from exc
    if value < 1:
        raise DialerError("RVA_DIALER_MAX_RETRIES must be at least 1")
    return value


def _max_contacts() -> int:
    raw = _env("RVA_DIALER_MAX_CONTACTS")
    if raw is None:
        return 32
    try:
        value = int(raw)
    except ValueError as exc:
        raise DialerError("RVA_DIALER_MAX_CONTACTS must be an integer") from exc
    if value < 1:
        raise DialerError("RVA_DIALER_MAX_CONTACTS must be at least 1")
    return value


def build_endpoint(msisdn: str) -> str:
    template = _env("RVA_DIALER_ENDPOINT") or _DEFAULT_ENDPOINT
    digits = msisdn[1:]
    try:
        return template.format(digits=digits, msisdn=msisdn)
    except KeyError as exc:
        raise DialerError(f"RVA_DIALER_ENDPOINT placeholder missing: {exc}") from exc


def run_acme_campaign(
    client: AriClient,
    contacts: Sequence[CampaignContact],
    *,
    max_contacts: int | None = None,
    store: InMemoryDialerStore | None = None,
) -> list[OriginateResult]:
    limit = max_contacts if max_contacts is not None else _max_contacts()
    if len(contacts) > limit:
        raise DialerError(f"campaign has {len(contacts)} rows; limit is {limit}")
    job_store = store if store is not None else InMemoryDialerStore()
    job_store.enqueue_contacts(contacts, max_attempts=max_attempts_from_env())
    jobs = run_campaign_jobs(client, job_store)
    results = [
        OriginateResult(
            msisdn=job.msisdn,
            channel_id=job.channel_id or "",
            endpoint=job.endpoint or "",
            audio_uuid=job.audio_uuid or "",
        )
        for job in jobs
        if job.state == JobState.DONE
    ]
    failed = [job for job in jobs if job.state == JobState.FAILED]
    if failed and not results:
        detail = "; ".join(f"{j.msisdn}: {j.last_error}" for j in failed)
        raise DialerError(f"all {len(failed)} job(s) failed: {detail}")
    if failed:
        detail = "; ".join(f"{j.msisdn}: {j.last_error}" for j in failed)
        raise DialerError(
            f"{len(failed)} job(s) failed after retries; {len(results)} done: {detail}",
            originated=results,
        )
    return results


def run_acme_campaign_jobs(
    client: AriClient,
    contacts: Sequence[CampaignContact],
    *,
    max_contacts: int | None = None,
) -> list[dict[str, object]]:
    limit = max_contacts if max_contacts is not None else _max_contacts()
    if len(contacts) > limit:
        raise DialerError(f"campaign has {len(contacts)} rows; limit is {limit}")
    store = open_job_store()
    store.enqueue_contacts(contacts, max_attempts=max_attempts_from_env())
    jobs = run_campaign_jobs(client, store)
    failed = [job for job in jobs if job.state == JobState.FAILED]
    results = [job_to_dict(job) for job in jobs]
    if failed:
        detail = "; ".join(f"{j.msisdn}: {j.last_error}" for j in failed)
        done = [j for j in jobs if j.state == JobState.DONE]
        if not done:
            raise DialerError(f"all {len(failed)} job(s) failed: {detail}")
        raise DialerError(
            f"{len(failed)} job(s) failed after retries; {len(done)} done: {detail}",
            originated=[
                OriginateResult(
                    msisdn=j.msisdn,
                    channel_id=j.channel_id or "",
                    endpoint=j.endpoint or "",
                    audio_uuid=j.audio_uuid or "",
                )
                for j in done
            ],
        )
    return results
