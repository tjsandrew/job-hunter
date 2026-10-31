"""Lambda entry point that loads a job snapshot into the database (``job_hunter.import_worker.handler``).

It runs INSIDE the VPC, because only there can it reach Aurora. The discovery Lambda (outside the VPC) writes the snapshot
``imports/<pull id>.json`` to the documents bucket and invokes this function with ``{"bucket", "key", "max_new"}``. The
function reads the object through the S3 gateway endpoint, inserts at most ``max_new`` NEW jobs (jobs already stored are
refreshed as usual), and writes the embed flag after the commit so the embed worker gives the new jobs vectors.

Database role: ``jobhunter_app`` (the shared ``jobs`` table has no row-level security). Environment: DOCUMENT_BUCKET,
DATABASE_HOST, DATABASE_NAME, DATABASE_USERNAME, DATABASE_PASSWORD (set by the release), APP_ENV=aws.
"""
from __future__ import annotations

import json
import logging
import os

from job_hunter.job_pull import IMPORT_PREFIX, MAX_SNAPSHOT_BYTES, clamp_max_new, interleave

DB_ROLE = "jobhunter_app"
log = logging.getLogger(__name__)
_engine = None


def build_engine():
    from job_hunter.adapters.aws_config import password_engine
    return password_engine(os.environ["DATABASE_HOST"], os.getenv("DATABASE_NAME", "jobhunter"),
                           os.getenv("DATABASE_USERNAME") or DB_ROLE, attempts=25)   # ~2.5 minutes: Aurora may be resuming (81 s seen)


def read_report(s3, bucket: str, key: str):
    from job_hunter.import_jobs import report_from_payload
    if bucket != os.getenv("DOCUMENT_BUCKET") or not key.startswith(IMPORT_PREFIX) or not key.endswith(".json") or ".." in key:
        raise ValueError("snapshot must be a .json object under the imports/ prefix of the documents bucket")
    data = s3.get_object(Bucket=bucket, Key=key)["Body"].read(MAX_SNAPSHOT_BYTES + 1)
    if len(data) > MAX_SNAPSHOT_BYTES:
        raise ValueError("snapshot is too large")
    return report_from_payload(json.loads(data))


def load(session, report, max_new: int):
    """Insert the next ``max_new`` new jobs of the snapshot in the caller's transaction."""
    from job_hunter.import_jobs import SQLAlchemyJobRepository, import_report
    report.jobs = interleave(report.jobs)      # a small batch mixes sources and employers
    return import_report(SQLAlchemyJobRepository(session), report, max_new=max_new)


def summary(stats, *, fetched: int, flagged: bool) -> dict:
    return {"snapshot_records": fetched, "new": stats.new, "updated": stats.updated, "unchanged": stats.unchanged,
            "deferred": stats.deferred, "duplicate_links_changed": stats.linked, "reopened": stats.reopened,
            "closed_expired": stats.closed_expired, "closed_unseen": stats.closed_unseen, "errors": stats.errors, "record_errors": stats.record_errors[:5],
            "embed_flag_written": flagged}


def handler(event, context=None):
    global _engine
    import boto3
    from sqlalchemy.orm import Session
    from job_hunter.embedding import flag

    logging.getLogger().setLevel(logging.INFO)
    if not isinstance(event, dict) or not event.get("bucket") or not event.get("key"):
        raise ValueError("event must name the snapshot: {\"bucket\": ..., \"key\": ..., \"max_new\": ...}")
    s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION") or "ap-southeast-1")
    report = read_report(s3, str(event["bucket"]), str(event["key"]))
    fetched = len(report.jobs)
    if _engine is None:
        _engine = build_engine()
    with Session(_engine) as session:
        with session.begin():
            stats = load(session, report, clamp_max_new(event.get("max_new")))
    # Only after the commit: written earlier, the embed worker could run before the new rows are visible.
    flagged = flag.write_flag() if stats.new else False
    return summary(stats, fetched=fetched, flagged=flagged)
