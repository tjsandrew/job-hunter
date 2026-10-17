"""Backfill: embed every open job and every user's confirmed profile version.

Callable from code (``backfill_jobs`` / ``backfill_profiles``) or from the command line::

    python -m job_hunter.embedding.backfill [--jobs] [--profiles] [--user alice] [--limit N] [--force]
    python -m job_hunter.embedding.backfill --text-report [--limit N]     # read-only, embeds nothing

It is idempotent: anything whose text, text version and model are unchanged is skipped, and jobs or profiles
that are pending or failed are retried. The embedder being down never raises; those items stay pending.

The functions own the transaction (they commit after each batch / user); the embedding functions underneath
never commit. Profiles are row-level-secured, so the per-user setting is applied inside each user's own
transaction. In local mode the users come from the development identity map; a cloud deployment will need
its own way to list users and should pass ``user_ids`` explicitly.
"""

from __future__ import annotations

import argparse
import os
from collections import Counter
from typing import Callable, Iterable, Sequence

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from job_hunter.config import settings as app_settings
from job_hunter.domain.models import Job

from . import settings as embedding_settings
from .client import HttpEmbedder
from .db_store import DbJobEmbeddingStore
from .job_text import JobTextInput, section_stats
from .pipeline import JobEmbedRequest, embed_jobs
from .profile_sync import NO_CONFIRMED_PROFILE, embed_user_profile


def backfill_jobs(session: Session, embedder, *, batch_size: int = 32, limit: int | None = None,
                  force: bool = False, log: Callable[[str], None] = lambda message: None) -> Counter:
    """Embed open jobs in batches; returns a count per outcome status."""
    query = select(Job).where(Job.status == "open").order_by(Job.id)
    if limit:
        query = query.limit(limit)
    jobs = list(session.scalars(query))
    store, counts = DbJobEmbeddingStore(session), Counter()
    for start in range(0, len(jobs), batch_size):
        chunk = jobs[start:start + batch_size]
        requests = [JobEmbedRequest(job_id=str(job.id), job=JobTextInput.from_job(job))
                    for job in chunk]
        for outcome in embed_jobs(requests, embedder=embedder, store=store, force=force, batch_size=batch_size):
            counts[outcome.status] += 1
        session.commit()
        log(f"jobs {min(start + batch_size, len(jobs))}/{len(jobs)}: {dict(counts)}")
    return counts


def text_report(session: Session, *, limit: int | None = None) -> dict:
    """How well heading detection would do on the open jobs, per source. Read-only; embeds nothing.

    The default job text uses the whole description, so this is for judging whether heading
    detection (job-v1 / job-v3) could be trusted on a new source: how many listings it would use
    sections for, how many fall back, why, and how much of the description it keeps."""
    query = select(Job).where(Job.status == "open").order_by(Job.id)
    if limit:
        query = query.limit(limit)
    report: dict = {}
    for job in session.scalars(query):
        source = f"{job.source}/{job.source_board}" if job.source_board else job.source
        row = report.setdefault(source, {"jobs": 0, "v1_uses_sections": 0, "v3_uses_sections": 0, "kept_share_sum": 0.0,
                                         "fallback_reasons": Counter()})
        v1, v3 = section_stats(job.description), section_stats(job.description, tolerant=True)
        row["jobs"] += 1
        row["v1_uses_sections"] += v1.used_sections
        row["v3_uses_sections"] += v3.used_sections
        row["kept_share_sum"] += v1.kept_share if v1.used_sections else 0.0
        if not v3.used_sections:
            row["fallback_reasons"][v3.fallback_reason or "unknown"] += 1
    for row in report.values():
        used, share_sum = row["v1_uses_sections"], row.pop("kept_share_sum")
        row["avg_kept_share_v1"] = round(share_sum / used, 2) if used else None
        row["fallback_reasons"] = dict(row["fallback_reasons"])
    return report


def backfill_profiles(session: Session, embedder, user_ids: Iterable, *, force: bool = False,
                      log: Callable[[str], None] = lambda message: None) -> Counter:
    """Embed each user's confirmed profile version, one transaction per user."""
    counts = Counter()
    for user_id in user_ids:
        session.execute(text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": str(user_id)})
        outcome = embed_user_profile(session, user_id, embedder, force=force)
        if outcome is None:
            counts[NO_CONFIRMED_PROFILE] += 1
            log(f"user {user_id}: no confirmed profile version")
        else:
            counts[outcome.status] += 1
            log(f"user {user_id}: {outcome.status}" + (f" ({outcome.reason})" if outcome.reason else ""))
        session.commit()
    return counts


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Embed open jobs and confirmed profile versions.")
    parser.add_argument("--jobs", action="store_true", help="only jobs")
    parser.add_argument("--profiles", action="store_true", help="only profiles")
    parser.add_argument("--user", action="append", help="development user key (default: all); repeatable")
    parser.add_argument("--limit", type=int, help="at most this many jobs")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--force", action="store_true", help="re-embed even if unchanged")
    parser.add_argument("--text-report", action="store_true",
                        help="read-only: how heading detection would do per source (embeds nothing)")
    args = parser.parse_args(argv)
    do_jobs, do_profiles = args.jobs or not args.profiles, args.profiles or not args.jobs

    from job_hunter.domain.identity import DEV_USERS   # local-mode user list

    keys = args.user or list(DEV_USERS)
    unknown = [key for key in keys if key not in DEV_USERS]
    if unknown:
        parser.error(f"unknown user key(s): {', '.join(unknown)}")
    engine = create_engine(os.getenv("MIGRATION_DATABASE_URL") or app_settings.database_url)
    embedder = HttpEmbedder(embedding_settings.embedder_url(), timeout_seconds=120)
    with Session(engine) as session:
        if args.text_report:
            for source, row in sorted(text_report(session, limit=args.limit).items()):
                print(f"{source}: {row}")
            return 0
        if do_jobs:
            print("jobs:", dict(backfill_jobs(session, embedder, batch_size=args.batch_size, limit=args.limit,
                                              force=args.force, log=print)))
        if do_profiles:
            print("profiles:", dict(backfill_profiles(session, embedder, [DEV_USERS[key][0] for key in keys],
                                                      force=args.force, log=print)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
