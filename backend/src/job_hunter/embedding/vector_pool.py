"""An in-memory copy of the job vectors For you compares against, one per API process (each Lambda instance).

Each For you request used to load every listed job's 512-number vector from Aurora and compare them one by one in Python,
which took seconds once the pool reached thousands of jobs. This keeps the vectors (and each job's eligibility fields) in a
numpy matrix and computes every similarity in one matrix product. Like ``job_pool``, it is rebuilt when anything changes: the
jobs fingerprint (``job_pool.jobs_signature``) or the ready vectors for this model and text version (count and latest update).
Which jobs a request may consider is decided per request with the same rule as ``listed_jobs``, and the checks and ranking
in ``retrieval.retrieve`` are unchanged, so For you results match the database path. ``JOB_POOL_CACHE=0`` turns it off.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import threading
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from job_hunter import job_pool
from job_hunter.domain.models import Job, now_utc
from job_hunter.role_family import classify_engineering_subrole

from .db_tables import job_embeddings
from .features import job_role_family, job_seniority_levels
from .retrieval import RetrievalCandidate
from .stores import STATUS_READY


@dataclass(frozen=True)
class _Entry:
    job: dict[str, Any]                 # eligibility fields, as load_job_candidates returns them
    candidate: RetrievalCandidate       # vector left empty: similarities come from the matrix
    status: str
    duplicate: bool
    posted_at: datetime | None
    expires_at: datetime | None


@dataclass(frozen=True)
class _Pool:
    signature: tuple
    entries: tuple[_Entry, ...]
    matrix: np.ndarray                  # one row per entry, float64 like the Python cosine it replaces
    norms: np.ndarray


_pools: dict[tuple[str, str], _Pool] = {}
_lock = threading.Lock()


def _vectors_signature(db: Session, model: str, text_version: str) -> tuple:
    return tuple(db.execute(
        select(func.count(), func.max(job_embeddings.c.updated_at))
        .where(job_embeddings.c.model == model, job_embeddings.c.text_version == text_version,
               job_embeddings.c.status == STATUS_READY)).one())


def _rebuild(db: Session, model: str, text_version: str, signature: tuple) -> _Pool:
    rows = db.execute(
        select(Job.id, Job.title, Job.company, Job.location, Job.work_mode, Job.status, Job.category, Job.seniority,
               Job.salary_min, Job.salary_max, Job.salary_currency, Job.salary_period, Job.canonical_job_id, Job.posted_at,
               Job.expires_at, job_embeddings.c.embedding)
        .join(job_embeddings, job_embeddings.c.job_id == Job.id)
        .where(job_embeddings.c.text_version == text_version, job_embeddings.c.status == STATUS_READY,
               job_embeddings.c.model == model)).all()
    entries, vectors = [], []
    for (job_id, title, company, location, work_mode, status, category, seniority, salary_min, salary_max, salary_currency,
         salary_period, canonical_job_id, posted_at, expires_at, embedding) in rows:
        job = {"id": str(job_id), "title": title, "company": company, "location": location, "work_mode": work_mode,
               "status": status, "category": category, "salary_min": salary_min, "salary_max": salary_max,
               "salary_currency": salary_currency, "salary_period": salary_period}
        candidate = RetrievalCandidate(job_id=str(job_id), vector=(), role_family=job_role_family(category),
                                       seniority_levels=job_seniority_levels(seniority),
                                       engineering_subrole=classify_engineering_subrole(title))
        entries.append(_Entry(job, candidate, status, canonical_job_id is not None, posted_at, expires_at))
        vectors.append(np.asarray(embedding, dtype=np.float64))
    matrix = np.vstack(vectors) if vectors else np.zeros((0, 0))
    return _Pool(signature, tuple(entries), matrix, np.linalg.norm(matrix, axis=1) if vectors else np.zeros(0))


def _pool(db: Session, model: str, text_version: str) -> _Pool:
    signature = (job_pool.jobs_signature(db), _vectors_signature(db, model, text_version))
    key = (model, text_version)
    pool = _pools.get(key)
    if pool is None or pool.signature != signature:
        with _lock:
            pool = _pools.get(key)
            if pool is None or pool.signature != signature:
                pool = _pools[key] = _rebuild(db, model, text_version, signature)
    return pool


def listed_candidates(db: Session, *, model: str, text_version: str, query_vector, posted_after: datetime | None = None,
                      include_closed: bool = False, now: datetime | None = None,
                      ) -> tuple[list[tuple[dict[str, Any], RetrievalCandidate]], dict[str, float]]:
    """The listed jobs with a ready vector (as ``load_job_candidates`` returns them) and each one's cosine similarity to
    ``query_vector``, computed in one matrix product."""
    pool, now = _pool(db, model, text_version), now or now_utc()
    keep = [index for index, entry in enumerate(pool.entries)
            if job_pool.is_listed(status=entry.status, duplicate=entry.duplicate, posted_at=entry.posted_at,
                                  expires_at=entry.expires_at, now=now, posted_after=posted_after,
                                  include_closed=include_closed)]
    if not keep:
        return [], {}
    query = np.asarray(query_vector, dtype=np.float64)
    if query.shape[0] != pool.matrix.shape[1]:
        raise ValueError("vectors must have the same number of dimensions")
    query_norm = float(np.linalg.norm(query))
    dots, norms = pool.matrix[keep] @ query, pool.norms[keep] * query_norm
    similarities = np.divide(dots, norms, out=np.zeros_like(dots), where=norms != 0)
    entries = [pool.entries[index] for index in keep]
    return ([(entry.job, entry.candidate) for entry in entries],
            {entry.candidate.job_id: float(value) for entry, value in zip(entries, similarities)})


def clear() -> None:
    """Forget every copy (tests)."""
    _pools.clear()
