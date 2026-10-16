"""Backfill: embed every open job and every user's confirmed profile version.

Callable from code (``backfill_jobs`` / ``backfill_profiles``) or from the command line::

    python -m job_hunter.embedding.backfill [--jobs] [--profiles] [--user alice] [--limit N] [--force]

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
from job_hunter.domain.models import Job, Preference, Profile, ProfileVersion

from . import settings as embedding_settings
from .client import HttpEmbedder
from .db_store import DbJobEmbeddingStore, DbProfileEmbeddingStore
from .job_text import JobTextInput
from .pipeline import JobEmbedRequest, ProfileEmbedRequest, embed_jobs, embed_profile
from .profile_text import ProfileTextInput

NO_CONFIRMED_PROFILE = "no_confirmed_profile"


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
        requests = [JobEmbedRequest(job_id=str(job.id), job=JobTextInput.from_job(job), category=job.category)
                    for job in chunk]
        for outcome in embed_jobs(requests, embedder=embedder, store=store, force=force, batch_size=batch_size):
            counts[outcome.status] += 1
        session.commit()
        log(f"jobs {min(start + batch_size, len(jobs))}/{len(jobs)}: {dict(counts)}")
    return counts


def backfill_profiles(session: Session, embedder, user_ids: Iterable, *, force: bool = False,
                      log: Callable[[str], None] = lambda message: None) -> Counter:
    """Embed each user's confirmed profile version, one transaction per user."""
    store, counts = DbProfileEmbeddingStore(session), Counter()
    for user_id in user_ids:
        session.execute(text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": str(user_id)})
        profile = session.get(Profile, user_id)
        version = None
        if profile is not None and profile.confirmed_revision is not None:
            version = session.scalar(select(ProfileVersion).where(
                ProfileVersion.user_id == user_id, ProfileVersion.revision == profile.confirmed_revision))
        if version is None:
            counts[NO_CONFIRMED_PROFILE] += 1
            log(f"user {user_id}: no confirmed profile version")
            session.commit()
            continue
        preferences = session.get(Preference, user_id)
        data = preferences.data if preferences else {}
        outcome = embed_profile(
            ProfileEmbedRequest(profile_version_id=str(version.id), snapshot=version.data,
                                target_roles=ProfileTextInput.from_preferences({}, data).target_roles,
                                seniority_preference=data.get("seniority")),
            embedder=embedder, store=store, force=force)
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
        if do_jobs:
            print("jobs:", dict(backfill_jobs(session, embedder, batch_size=args.batch_size, limit=args.limit,
                                              force=args.force, log=print)))
        if do_profiles:
            print("profiles:", dict(backfill_profiles(session, embedder, [DEV_USERS[key][0] for key in keys],
                                                      force=args.force, log=print)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
