"""Load candidates and a profile query from the embedding tables, then run the in-memory retrieval.

Like ``db_store``, this takes the caller's SQLAlchemy ``Session`` (so per-user row-level security
applies) and never commits. Exact, in-memory similarity is used on purpose: at proof-of-concept scale
(hundreds to low thousands of jobs) it is simple, exact and needs no vector index. A pgvector query can
replace ``retrieve`` later without changing the callers.

Vectors from different models are never compared: the jobs considered are exactly those embedded with
the same model, and the same text version, as the profile's vector.

``recommend_for_profile`` returns ``None`` when the profile has no usable vector. That is the signal for
the caller to fall back to the existing keyword ranker.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_hunter.domain.models import Job, ProfileVersion, listed_jobs
from job_hunter.role_family import classify_engineering_subrole

from .db_tables import job_embeddings, profile_embeddings
from .features import Classifier, extract_profile_features, job_role_family, job_seniority_levels, role_hint_from_snapshot
from .job_text import JOB_TEXT_VERSION
from .profile_text import PROFILE_TEXT_VERSION, ProfileTextInput
from .retrieval import ProfileQuery, RetrievalCandidate, RetrievalResult, eligible_jobs, retrieve
from .stores import STATUS_READY
from .db_store import _uuid


def _floats(value: Any) -> tuple[float, ...]:
    return tuple(float(x) for x in value)


def load_profile_query(session: Session, profile_version_id: str, *, target_roles: Sequence[str] | None,
                       seniority_preference: str | Sequence[str] | None, text_version: str = PROFILE_TEXT_VERSION,
                       classify: Classifier | None = None) -> tuple[ProfileQuery, str] | None:
    """The profile's vector and checks inputs, plus the model that produced the vector."""
    row = session.execute(
        select(profile_embeddings.c.embedding, profile_embeddings.c.model).where(
            profile_embeddings.c.profile_version_id == _uuid(profile_version_id),
            profile_embeddings.c.text_version == text_version,
            profile_embeddings.c.status == STATUS_READY)).first()
    if row is None or row[0] is None or not row[1]:
        return None
    features = extract_profile_features(target_roles, seniority_preference, classify)
    query = ProfileQuery(vector=_floats(row[0]), role_families=features.role_families,
                         seniority_levels=features.seniority_levels,
                         engineering_subroles=features.engineering_subroles)
    return query, row[1]


def load_job_candidates(session: Session, *, model: str, text_version: str = JOB_TEXT_VERSION,
                        posted_after: datetime | None = None) -> list[tuple[dict[str, Any], RetrievalCandidate]]:
    """Every job with a ready vector for this model and text version, with its eligibility fields.

    Only jobs Discover lists are loaded (``listed_jobs``): a closed or expired job, or a duplicate of another source's posting
    (``jobs.canonical_job_id`` set), is left out; users see the canonical row.

    A job's role family and seniority are read from the job row (``jobs.category``, ``jobs.seniority``), where
    ingestion put them. An empty, unknown or not-yet-classified value counts as unknown / open to all levels, so
    it never blocks a job."""
    rows = session.execute(
        select(Job.id, Job.title, Job.company, Job.location, Job.work_mode, Job.status, Job.category,
               Job.seniority, Job.salary_min, Job.salary_max, Job.salary_currency, Job.salary_period,
               job_embeddings.c.embedding)
        .join(job_embeddings, job_embeddings.c.job_id == Job.id)
        .where(job_embeddings.c.text_version == text_version, job_embeddings.c.status == STATUS_READY,
               job_embeddings.c.model == model, listed_jobs(posted_after=posted_after))).all()
    loaded = []
    for (job_id, title, company, location, work_mode, status, category, seniority, salary_min, salary_max,
         salary_currency, salary_period, embedding) in rows:
        job = {"id": str(job_id), "title": title, "company": company, "location": location,
               "work_mode": work_mode, "status": status, "category": category, "salary_min": salary_min,
               "salary_max": salary_max, "salary_currency": salary_currency, "salary_period": salary_period}
        loaded.append((job, RetrievalCandidate(job_id=str(job_id), vector=_floats(embedding),
                                               role_family=job_role_family(category),
                                               seniority_levels=job_seniority_levels(seniority),
                                               engineering_subrole=classify_engineering_subrole(title))))
    return loaded


def recommend_for_profile(session: Session, profile_version_id: str, preferences: Mapping[str, Any] | None, *,
                          target_roles: Sequence[str] | None = None,
                          seniority_preference: str | Sequence[str] | None = None, limit: int | None = 10,
                          exclude_job_ids: Iterable[str] = (), apply_checks: bool = True,
                          classify: Classifier | None = None, job_text_version: str = JOB_TEXT_VERSION,
                          profile_text_version: str = PROFILE_TEXT_VERSION,
                          posted_after: datetime | None = None) -> RetrievalResult | None:
    """Eligibility, then role/seniority checks, then similarity. ``None`` means "no usable profile vector"."""
    preferences = preferences or {}
    if target_roles is None:
        target_roles = ProfileTextInput.from_preferences({}, preferences).target_roles
    if not target_roles:
        # No target roles set: the role check falls back to the profile's headline (or latest role).
        version = session.get(ProfileVersion, _uuid(profile_version_id))
        target_roles = role_hint_from_snapshot(version.data if version is not None else None)
    if seniority_preference is None:
        seniority_preference = preferences.get("seniority")
    loaded = load_profile_query(session, profile_version_id, target_roles=target_roles,
                                seniority_preference=seniority_preference, text_version=profile_text_version,
                                classify=classify)
    if loaded is None:
        return None
    query, model = loaded
    candidates = load_job_candidates(session, model=model, text_version=job_text_version, posted_after=posted_after)
    by_id = {job["id"]: candidate for job, candidate in candidates}
    eligible = eligible_jobs((job for job, _ in candidates), preferences, exclude_job_ids)
    return retrieve(query, (by_id[job["id"]] for job in eligible), limit=limit, apply_checks=apply_checks)
