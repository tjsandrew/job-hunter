"""One embedding pass for the AWS embed worker (see docs/design/11-EMBEDDING-WORKER.md).

``run_pass`` embeds what the database says is pending, within a time budget:

1. take a Postgres advisory lock so overlapping runs cannot embed the same rows twice (a run that cannot
   take the lock returns ``busy``; the run that holds it releases the lock and then looks for pending
   work once more, so rows saved just before the release are still picked up);
2. embed pending jobs in small batches, committing after each batch, until none are left or the next
   batch would not fit in the time budget;
3. before every batch, look at the profiles first (the pipeline's hash check skips unchanged ones), so a
   profile saved during a long ingestion waits for one batch, not for the whole run.

The embedder is only called when there is something to embed, so a run with nothing to do never loads
the model. Only counts are logged, never text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import time
from typing import Callable
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from job_hunter.domain.models import Job

from .db_store import DbJobEmbeddingStore
from .job_text import JOB_TEXT_VERSION, JobTextInput
from .pending import confirmed_profile_user_ids, pending_job_ids, touch_job_embeddings
from .pipeline import STATUS_READY, STATUS_UNCHANGED, JobEmbedRequest, embed_jobs
from .profile_sync import embed_user_profile

# The migration function uses 5224001; keep this one distinct.
LOCK_KEY = 5224002
log = logging.getLogger(__name__)


@dataclass
class PassResult:
    busy: bool = False
    profiles: dict[str, int] = field(default_factory=dict)
    jobs: dict[str, int] = field(default_factory=dict)
    progress: int = 0        # previously pending items that now have a vector
    remaining: bool = False  # pending jobs were left because time ran out
    batches: int = 0

    def summary(self) -> dict:
        return {"busy": self.busy, "profiles": dict(self.profiles), "jobs": dict(self.jobs),
                "progress": self.progress, "remaining": self.remaining, "batches": self.batches}


def _count(target: dict[str, int], status: str) -> None:
    target[status] = target.get(status, 0) + 1


def _try_lock(connection) -> bool:
    return bool(connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}).scalar())


def _unlock(connection) -> None:
    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})


def _jobs_pending(engine, *, text_version: str, model: str | None, everything: bool) -> bool:
    with Session(engine) as session:
        found = bool(pending_job_ids(session, text_version=text_version, model=model, limit=1,
                                     everything=everything))
        session.rollback()
        return found


def _embed_profiles(engine, embedder, result: PassResult, *, model, force, out_of_time,
                    count_unchanged: bool = True) -> None:
    with Session(engine) as session:
        user_ids = confirmed_profile_user_ids(session)
        session.commit()
        for user_id in user_ids:
            if out_of_time():
                return
            # Per-user row-level security context, exactly as the CLI backfill does.
            session.execute(text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": str(user_id)})
            outcome = embed_user_profile(session, user_id, embedder, force=force, expected_model=model)
            session.commit()
            if outcome is not None:
                if count_unchanged or outcome.status != STATUS_UNCHANGED:
                    _count(result.profiles, outcome.status)
                if outcome.status == STATUS_READY:
                    result.progress += 1


def _embed_jobs(engine, embedder, result: PassResult, *, text_version, model, force, batch_size,
                clock: Callable[[], float], deadline: float, profiles_step: Callable[[], None]) -> None:
    cursor: UUID | None = None
    slowest = 0.0  # longest batch so far; the next one must fit before the deadline
    while True:
        # Profiles first, before EVERY batch: a user who saves a profile during a long ingestion waits for the
        # current batch at most, not for the whole run. (The save's own flag finds the lock held and exits; this
        # check is what picks the profile up.) It costs a few small queries per batch.
        profiles_step()
        if clock() + slowest >= deadline:
            result.remaining = _jobs_pending(engine, text_version=text_version, model=model, everything=False) \
                if not force else True
            return
        started = clock()
        with Session(engine) as session:
            ids = pending_job_ids(session, text_version=text_version, model=model, limit=batch_size,
                                  after_id=cursor, everything=force)
            if not ids:
                session.rollback()
                return
            cursor = ids[-1]
            jobs = list(session.scalars(select(Job).where(Job.id.in_(ids)).order_by(Job.id)))
            requests = [JobEmbedRequest(job_id=str(job.id), job=JobTextInput.from_job(job)) for job in jobs]
            outcomes = embed_jobs(requests, embedder=embedder, store=DbJobEmbeddingStore(session),
                                  expected_model=model, force=force, batch_size=max(1, len(requests)),
                                  text_version=text_version)
            unchanged = [job.id for job, outcome in zip(jobs, outcomes) if outcome.status == STATUS_UNCHANGED]
            touch_job_embeddings(session, unchanged, text_version)
            session.commit()
        for outcome in outcomes:
            _count(result.jobs, outcome.status)
            if outcome.status == STATUS_READY:
                result.progress += 1
        result.batches += 1
        slowest = max(slowest, clock() - started)


def run_pass(engine, embedder, *, model: str | None, deadline: float, batch_size: int = 8, force: bool = False,
             clock: Callable[[], float] = time.monotonic, text_version: str = JOB_TEXT_VERSION) -> PassResult:
    """Embed what is pending until nothing is left or ``deadline`` (a ``clock()`` value) is near."""
    result = PassResult()
    # A dedicated autocommit connection holds the session-level lock for the whole run.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as lock_connection:
        if not _try_lock(lock_connection):
            result.busy = True
            return result
        locked = True
        try:
            while True:
                out_of_time = lambda: clock() >= deadline  # noqa: E731
                progress_before = result.progress
                first_profile_check = [True]

                def profiles_step():
                    # A forced run re-embeds each profile once; later checks only look for new work and only
                    # report profiles that were actually embedded.
                    _embed_profiles(engine, embedder, result, model=model, force=force and first_profile_check[0],
                                    out_of_time=out_of_time, count_unchanged=first_profile_check[0])
                    first_profile_check[0] = False

                _embed_jobs(engine, embedder, result, text_version=text_version, model=model, force=force,
                            batch_size=batch_size, clock=clock, deadline=deadline, profiles_step=profiles_step)
                force = False  # a forced run is one full sweep, not a loop
                _unlock(lock_connection)
                locked = False
                # Release first, then look once more: anything saved before the release is seen here, anything
                # saved after it wakes a new invocation that can take the lock.
                if result.remaining or out_of_time() or result.progress == progress_before:
                    break   # out of time, or the last round embedded nothing new (no endless loop)
                if not _jobs_pending(engine, text_version=text_version, model=model, everything=False):
                    break
                if not _try_lock(lock_connection):
                    break
                locked = True
        finally:
            if locked:
                _unlock(lock_connection)
    log.info("embedding pass: %s", result.summary())
    return result
