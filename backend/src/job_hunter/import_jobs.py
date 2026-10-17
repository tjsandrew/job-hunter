"""One-shot CLI to discover and transactionally upsert public job-board records.

This command deliberately uses MIGRATION_DATABASE_URL, the local database owner
connection, because jobs form a shared pool rather than tenant-owned API data.
It is not invoked from the API runtime.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_hunter.ingestion.discovery import DiscoveryConfig, DiscoveryReport, discover_report
from job_hunter.job_classification import classify_job
from job_hunter.role_family import CLASSIFIER_VERSION, classify_role_family
from job_hunter.seniority import SENIORITY_STATED

logger = logging.getLogger(__name__)


@dataclass
class ImportStats:
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: int = 0
    source_failures: list[dict[str, str]] = field(default_factory=list)
    truncated_boards: list[str] = field(default_factory=list)
    record_errors: list[dict[str, str]] = field(default_factory=list)


class JobRepository(Protocol):
    def find(self, source: str, source_board: str | None, external_id: str) -> Any | None: ...
    def add(self, job: Any) -> None: ...


class SQLAlchemyJobRepository:
    def __init__(self, session: Session, job_model: type | None = None) -> None:
        if job_model is None:
            job_model = _load_job_model()
        self.session = session
        self.job_model = job_model

    def find(self, source: str, source_board: str | None, external_id: str) -> Any | None:
        statement = select(self.job_model).where(
            self.job_model.source == source,
            self.job_model.source_board == source_board,
            self.job_model.external_id == external_id,
        )
        return self.session.scalar(statement)

    def add(self, job: Any) -> None:
        self.session.add(job)


CONTENT_FIELDS = (
    "source_board",
    "source_url",
    "title",
    "company",
    "location",
    "work_mode",
    "description",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
    "posted_at",
    "expires_at",
    "category",
    "category_source",
    "category_evidence",
    "seniority",
    "seniority_source",
    "seniority_evidence",
    "dedup_key",
    "status",
)


def _load_job_model() -> type:
    # Keep the pure upsert logic testable without importing PostgreSQL pgvector
    # until the real ORM is required by the CLI.
    from job_hunter.domain.models import Job

    return Job


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# Title-only inference with the shared role-family classifier (``job_hunter.role_family``), which is also what
# the recommender uses, so ``jobs.category`` and the recommender's role family always agree. These values are
# explicitly marked as inferred; category evidence is the exact matched phrase from the listing title.
def classify_title(title: str) -> tuple[str, str, str | None]:
    """Return (category, source label, title evidence); categories are inferred."""
    category, evidence = classify_role_family(title)
    return category, CLASSIFIER_VERSION, evidence


def reclassify_jobs(jobs: Iterable[Any]) -> dict[str, int]:
    """Recompute category and seniority from each job's title, in place (no source fetch).

    Use it after the keyword tables in ``role_family.py`` / ``seniority.py`` change, or to fill rows that were
    never classified. A level the job source itself stated (``seniority_source == "stated"``) is kept."""
    counts = {"jobs": 0, "updated": 0, "unchanged": 0, "kept_stated_seniority": 0}
    for job in jobs:
        counts["jobs"] += 1
        title = job.title or ""
        values: dict[str, Any] = classify_job(title)
        if job.seniority_source == SENIORITY_STATED and job.seniority is not None:
            counts["kept_stated_seniority"] += 1
            for field_name in ("seniority", "seniority_source", "seniority_evidence"):
                values.pop(field_name)
        changed = {key: value for key, value in values.items() if getattr(job, key, None) != value}
        for key, value in changed.items():
            setattr(job, key, value)
        if changed:
            if hasattr(job, "updated_at"):
                job.updated_at = _now_utc()
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1
    return counts


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _job_values(record: Mapping[str, Any], job_model: type) -> dict[str, Any]:
    required = ("source", "external_id", "title", "source_url", "dedup_key")
    missing = [key for key in required if not record.get(key)]
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")

    # Missing optional data stays null; do not infer a location or work mode.
    values: dict[str, Any] = {
        "source": str(record["source"]),
        "external_id": str(record["external_id"]),
        "dedup_key": str(record["dedup_key"]),
        "title": str(record["title"]).strip(),
        "company": str(record["employer"]).strip() if record.get("employer") else None,
        "location": str(record["location"]).strip() if record.get("location") else None,
        "work_mode": str(record["work_mode"]).strip() if record.get("work_mode") else None,
        "description": record.get("description"),
        "url": str(record["source_url"]),
        "status": "open",
        "salary_min": record.get("salary_min"),
        "salary_max": record.get("salary_max"),
        "salary_currency": record.get("salary_currency"),
        "salary_period": record.get("salary_period"),
        "posted_at": _parse_datetime(record.get("posted_at")),
        "expires_at": _parse_datetime(record.get("expires_at")),
    }
    values.update(classify_job(values["title"], stated_seniority=record.get("stated_seniority")))
    available = set(job_model.__mapper__.attrs.keys())
    values["source_board"] = record.get("source_board")
    values["source_url"] = record["source_url"]
    values["fetched_at"] = _parse_datetime(record.get("fetched_at"))
    for attr in values:
        if attr not in available:
            raise RuntimeError(f"Job schema is missing required import column {attr!r}")
    if not values["title"]:
        raise ValueError("title is blank")
    if len(values["title"]) > 240:
        raise ValueError("title exceeds the 240 character database limit")
    if values["company"] is not None and len(values["company"]) > 200:
        raise ValueError("employer exceeds the 200 character database limit")
    if values["location"] is not None and len(values["location"]) > 200:
        raise ValueError("location exceeds the 200 character database limit")
    if values["work_mode"] is not None and len(values["work_mode"]) > 40:
        raise ValueError("work mode exceeds the 40 character database limit")
    if len(values["external_id"]) > 255 or len(values["dedup_key"]) > 500:
        raise ValueError("source identity exceeds the database limit")
    return values


def _record_error(record: Mapping[str, Any], reason: str) -> dict[str, str]:
    return {
        "source": str(record.get("source") or "unknown"),
        "external_id": str(record.get("external_id") or "unknown"),
        "error": reason,
    }


def upsert_records(
    repository: JobRepository,
    records: Sequence[Mapping[str, Any]],
    *,
        job_model: type | None = None,
) -> ImportStats:
    """Apply normalized records inside the caller's transaction."""
    stats = ImportStats()
    job_model = job_model or _load_job_model()
    for record in records:
        try:
            values = _job_values(record, job_model)
            existing = repository.find(
                values["source"], values.get("source_board"), values["external_id"]
            )
            if existing is None:
                repository.add(job_model(**values))
                stats.new += 1
                continue

            changed = any(getattr(existing, key) != values[key] for key in CONTENT_FIELDS)
            if changed:
                for key, value in values.items():
                    setattr(existing, key, value)
                if "updated_at" in job_model.__mapper__.attrs:
                    existing.updated_at = _now_utc()
                stats.updated += 1
            else:
                # Retrieval provenance advances even when listing content does not.
                if "fetched_at" in values:
                    existing.fetched_at = values["fetched_at"]
                stats.unchanged += 1
        except (ValueError, TypeError, OverflowError) as exc:
            stats.errors += 1
            stats.record_errors.append(_record_error(record, str(exc)))
    return stats


def import_report(
    repository: JobRepository,
    report: DiscoveryReport,
    *,
    location: str | None = None,
    job_model: type | None = None,
) -> ImportStats:
    records = report.jobs
    if location:
        wanted = location.casefold()
        records = [
            record for record in records
            if wanted in str(record.get("location") or "").casefold()
        ]
    stats = upsert_records(repository, records, job_model=job_model)
    stats.source_failures = list(report.failures)
    stats.truncated_boards = list(report.truncated_boards)
    stats.errors += len(report.failures)
    return stats


def save_snapshot(path: str | Path, report: DiscoveryReport) -> None:
    """Atomically save normalized jobs for re-import without another source fetch."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "snapshot_version": 1,
        "saved_at": _now_utc().isoformat().replace("+00:00", "Z"),
        "jobs": report.jobs,
        "failures": report.failures,
        "truncated_boards": report.truncated_boards,
    }
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def load_snapshot(path: str | Path) -> DiscoveryReport:
    """Load a previously saved normalized discovery result without network access."""
    source = Path(path)
    if source.stat().st_size > 50_000_000:
        raise ValueError("snapshot exceeds 50 MB")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping) or payload.get("snapshot_version") != 1:
        raise ValueError("unsupported job snapshot format")
    jobs = payload.get("jobs")
    failures = payload.get("failures", [])
    truncated = payload.get("truncated_boards", [])
    if not isinstance(jobs, list) or not all(isinstance(job, Mapping) for job in jobs):
        raise ValueError("snapshot jobs must be an array of records")
    if not isinstance(failures, list) or not isinstance(truncated, list):
        raise ValueError("snapshot failures and truncation state must be arrays")
    return DiscoveryReport(
        jobs=[dict(job) for job in jobs],
        failures=[dict(item) for item in failures if isinstance(item, Mapping)],
        truncated_boards=[str(item) for item in truncated],
    )


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover and import public employer job postings")
    parser.add_argument("--greenhouse", action="append", default=[], help="Greenhouse board token (repeatable)")
    parser.add_argument("--lever", action="append", default=[], help="Lever site token (repeatable)")
    parser.add_argument("--smartrecruiters", action="append", default=[], help="SmartRecruiters public company identifier (repeatable)")
    parser.add_argument("--location", help="keep records whose location contains this text")
    parser.add_argument("--snapshot-in", help="load normalized records without fetching providers")
    parser.add_argument(
        "--snapshot-out",
        default=os.getenv("JOB_IMPORT_CACHE_FILE", "/data/job-import-snapshots/latest.json"),
        help="cache normalized records before database import",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--max-records", type=int, default=1000)
    parser.add_argument("--singapore-only", action="store_true")
    parser.add_argument("--reclassify", action="store_true",
                        help="recompute category and seniority for every job from its title (no fetch, no import)")
    args = parser.parse_args(argv)
    args.greenhouse = args.greenhouse or [v.strip() for v in os.getenv("GREENHOUSE_BOARDS", "").split(",") if v.strip()]
    args.lever = args.lever or [v.strip() for v in os.getenv("LEVER_BOARDS", "").split(",") if v.strip()]
    args.smartrecruiters = args.smartrecruiters or [v.strip() for v in os.getenv("SMARTRECRUITERS_BOARDS", "").split(",") if v.strip()]
    if (not args.reclassify and not args.snapshot_in and not args.greenhouse and not args.lever
            and not args.smartrecruiters):
        parser.error("configure --greenhouse, --lever, or --smartrecruiters")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    from job_hunter.config import settings

    # The shared jobs pool is written with the owner/migration connection only.
    # Runtime credentials are never used as an implicit fallback.
    owner_url = settings.migration_database_url or os.getenv("MIGRATION_DATABASE_URL")
    if not owner_url:
        raise SystemExit("MIGRATION_DATABASE_URL is required for shared job imports")

    from sqlalchemy import create_engine

    if args.reclassify:
        engine = create_engine(owner_url, pool_pre_ping=True, pool_size=1, max_overflow=0)
        try:
            with Session(engine) as session:
                with session.begin():
                    job_model = _load_job_model()
                    counts = reclassify_jobs(session.scalars(select(job_model).order_by(job_model.id)))
        finally:
            engine.dispose()
        print(json.dumps({"reclassified": counts}, ensure_ascii=False, indent=2))
        return 0

    if args.snapshot_in:
        report = load_snapshot(args.snapshot_in)
    else:
        config = DiscoveryConfig(
            greenhouse_boards=args.greenhouse,
            lever_boards=args.lever,
            smartrecruiters_boards=args.smartrecruiters,
            timeout_seconds=args.timeout,
            page_size=args.page_size,
            max_pages_per_board=args.max_pages,
            max_records_per_board=args.max_records,
            singapore_only=args.singapore_only or bool(args.location and "singapore" in args.location.casefold()),
        )
        report = discover_report(config)
        if args.snapshot_out:
            save_snapshot(args.snapshot_out, report)
    engine = create_engine(owner_url, pool_pre_ping=True, pool_size=1, max_overflow=0)
    try:
        with Session(engine) as session:
            with session.begin():
                repository = SQLAlchemyJobRepository(session)
                stats = import_report(repository, report, location=args.location)
    except Exception:
        logger.exception("Job import transaction failed")
        raise
    finally:
        engine.dispose()

    output = {
        "discovered": len(report.jobs),
        "new": stats.new,
        "updated": stats.updated,
        "unchanged": stats.unchanged,
        "errors": stats.errors,
        "source_failures": stats.source_failures,
        "truncated_boards": stats.truncated_boards,
        "record_errors": stats.record_errors,
        "location_filter": args.location,
        "snapshot_in": args.snapshot_in,
        "snapshot_out": args.snapshot_out if not args.snapshot_in else None,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 1 if stats.errors else 0


if __name__ == "__main__":  # pragma: no cover - executable entry point
    raise SystemExit(main())
