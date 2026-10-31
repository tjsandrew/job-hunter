"""An in-memory copy of the job pool for Discover's lists, kept for as long as the process lives (one per API Lambda instance).

Every Discover request used to load every listed job, descriptions included, and rebuild its response shape. Jobs change only
when a pull runs, so this module keeps the rows and their shapes in memory and, on each request, asks the database one small
question instead: has anything that a list depends on changed? The answer is a fingerprint over every job's id, status,
duplicate link, dates and "also seen on" list, so a pull, a closure, a dedup relink or an edit all rebuild the copy on the next
request. Closing dates and the "Posted" window are still checked against the current time on every request.

The filtering here is the same rule as ``domain.models.listed_jobs`` (the SQL version), so a list is identical either way;
tests compare the two. Set ``JOB_POOL_CACHE=0`` to read from the database on every request instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
import threading
from typing import Any, Callable

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from job_hunter.domain.models import Job, listed_jobs, now_utc

# One short scan of the jobs table (a few milliseconds for thousands of rows) instead of loading every row and description.
SIGNATURE_SQL = text("""
    SELECT count(*), md5(coalesce(string_agg(
        concat_ws('|', id::text, status, canonical_job_id::text, updated_at::text, fetched_at::text, expires_at::text,
                  posted_at::text, also_seen_on::text), ',' ORDER BY id), ''))
    FROM jobs""")


@dataclass(frozen=True)
class _Row:
    job: dict[str, Any]           # the response shape (job_out); shared between requests, never mutated
    status: str
    posted_at: datetime | None
    expires_at: datetime | None
    duplicate: bool               # canonical_job_id is set: another source's row is the one users see


@dataclass(frozen=True)
class _Pool:
    signature: tuple
    rows: tuple[_Row, ...]


_pool: _Pool | None = None
_lock = threading.Lock()


def enabled() -> bool:
    return os.getenv("JOB_POOL_CACHE", "1").strip().casefold() not in {"0", "false", "no", "off"}


def _rebuild(db: Session, signature: tuple, job_out: Callable[[Job], dict]) -> _Pool:
    rows = tuple(_Row(job=job_out(job), status=job.status, posted_at=job.posted_at, expires_at=job.expires_at,
                      duplicate=job.canonical_job_id is not None)
                 for job in db.scalars(select(Job)))
    return _Pool(signature=signature, rows=rows)


def is_listed(*, status: str, duplicate: bool, posted_at: datetime | None, expires_at: datetime | None, now: datetime,
              posted_after: datetime | None, include_closed: bool) -> bool:
    """The rule of ``listed_jobs``: not a duplicate; open and not past its closing date unless closed ones are wanted;
    posted within the window, a job with no posting date always passing."""
    if duplicate:
        return False
    if not include_closed and (status != "open" or (expires_at is not None and expires_at <= now)):
        return False
    return posted_after is None or posted_at is None or posted_at >= posted_after


def _listed(row: _Row, now: datetime, posted_after: datetime | None, include_closed: bool) -> bool:
    return is_listed(status=row.status, duplicate=row.duplicate, posted_at=row.posted_at, expires_at=row.expires_at, now=now,
                     posted_after=posted_after, include_closed=include_closed)


def jobs_signature(db: Session) -> tuple:
    """The fingerprint of everything a Discover list depends on (also used by the For you vector cache)."""
    return tuple(db.execute(SIGNATURE_SQL).one())


def listed_job_rows(db: Session, job_out: Callable[[Job], dict], *, posted_after: datetime | None = None,
                    include_closed: bool = False, now: datetime | None = None) -> list[dict[str, Any]]:
    """The response shapes of the jobs a Discover list covers, in no particular order (the rankers sort them)."""
    global _pool
    now = now or now_utc()
    if not enabled():
        query = select(Job).where(listed_jobs(now=now, posted_after=posted_after, include_closed=include_closed))
        return [job_out(job) for job in db.scalars(query)]
    signature = jobs_signature(db)
    pool = _pool
    if pool is None or pool.signature != signature:
        with _lock:            # concurrent requests (a local server's threads) build it once
            pool = _pool
            if pool is None or pool.signature != signature:
                pool = _pool = _rebuild(db, signature, job_out)
    return [row.job for row in pool.rows if _listed(row, now, posted_after, include_closed)]


def clear() -> None:
    """Forget the copy (tests)."""
    global _pool
    _pool = None
