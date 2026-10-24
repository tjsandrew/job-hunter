"""What the AWS embed worker has to do: queries over database state (nothing is read from the S3 flag).

Jobs are shared data, so one SQL query finds the open jobs that need a (new) vector. Profiles are
protected by row-level security and there are few of them, so the worker lists the users with a confirmed
profile and lets the embedding pipeline's own hash check skip the unchanged ones.

A job is pending when, for the current text version, it has

* no embedding row, or
* a ``ready`` row from a different model, or from before the job was last updated, or
* a ``pending``/``failed`` row that is older than the job or older than the retry back-off, or
* a ``no_content`` row from before the job was last updated.

The SQL cannot compare the input hash (it is computed in Python), so "the job was updated after the
vector" is only a candidate test: the pipeline then returns ``unchanged`` and the caller refreshes the
row's timestamp with ``touch_job_embeddings`` so the job stops being a candidate. ``after_id`` walks the
ids in order, so a pass visits every job at most once even if a timestamp comparison stays true for a
moment (for example clock skew between the ingesting process and the database).

See docs/design/11-EMBEDDING-WORKER.md, section 4.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Sequence
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from job_hunter.domain.models import Job, Profile

from .db_tables import job_embeddings

RETRY_AFTER = timedelta(hours=1)


def pending_job_ids(session: Session, *, text_version: str, model: str | None, limit: int,
                    after_id: UUID | None = None, everything: bool = False,
                    retry_after: timedelta = RETRY_AFTER) -> list[UUID]:
    """Ids of open jobs that need embedding, in id order, strictly after ``after_id``.

    ``everything`` selects every open job (a forced run)."""
    e = job_embeddings.c
    query = (select(Job.id)
             .select_from(Job.__table__.outerjoin(
                 job_embeddings, and_(e.job_id == Job.id, e.text_version == text_version)))
             .where(Job.status == "open", Job.canonical_job_id.is_(None)))   # a duplicate needs no vector of its own
    if not everything:
        newer = Job.updated_at > e.updated_at
        ready_stale = and_(e.status == "ready", newer if model is None else or_(e.model.is_distinct_from(model), newer))
        retryable = and_(e.status.in_(("pending", "failed")),
                         or_(newer, e.updated_at < func.now() - retry_after))
        no_content = and_(e.status == "no_content", newer)
        query = query.where(or_(e.id.is_(None), ready_stale, retryable, no_content))
    if after_id is not None:
        query = query.where(Job.id > after_id)
    return list(session.scalars(query.order_by(Job.id).limit(limit)))


def touch_job_embeddings(session: Session, job_ids: Sequence[UUID], text_version: str) -> None:
    """Mark rows the pipeline found unchanged as checked now, so they stop being candidates."""
    if not job_ids:
        return
    session.execute(update(job_embeddings).where(job_embeddings.c.job_id.in_(list(job_ids)),
                                                 job_embeddings.c.text_version == text_version)
                    .values(updated_at=func.now()))


def confirmed_profile_user_ids(session: Session) -> list[UUID]:
    """Users whose profile has a confirmed version. Only the embed worker's role can see more than one."""
    return list(session.scalars(select(Profile.user_id)
                                .where(Profile.confirmed_revision.is_not(None))
                                .order_by(Profile.user_id)))
