"""Semantic "for you" recommendations for one user, with a reason when it cannot be used.

``semantic_for_you`` returns ``(result, reason)``. ``result`` is ``None`` (and ``reason`` says why) whenever the
caller should fall back to the keyword ranker: no confirmed profile, or no profile vector yet. A profile vector
from a different model than every job vector also yields an empty result, never a mixed comparison.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_hunter.domain.models import Job

from .db_retrieval import recommend_for_profile
from .features import FEATURES_VERSION
from .job_text import JOB_TEXT_VERSION
from .profile_text import PROFILE_TEXT_VERSION
from .retrieval import RetrievalResult

RANKING_VERSION = f"semantic:{JOB_TEXT_VERSION}+{PROFILE_TEXT_VERSION}+{FEATURES_VERSION}"
NO_PROFILE = "No confirmed profile yet, so the keyword ranker was used."
NO_VECTOR = "The profile has not been embedded yet (run the backfill), so the keyword ranker was used."


def semantic_for_you(db: Session, confirmed: "tuple[str, int, Any] | None", preferences: Mapping[str, Any] | None,
                     exclude_job_ids: Iterable[str] = ()) -> "tuple[RetrievalResult | None, str | None]":
    """``confirmed`` is ``(profile_version_id, revision, snapshot)`` or ``None``."""
    if confirmed is None:
        return None, NO_PROFILE
    result = recommend_for_profile(db, confirmed[0], preferences or {}, limit=None, exclude_job_ids=exclude_job_ids)
    if result is None:
        return None, NO_VECTOR
    return result, None


def page_items(db: Session, result: RetrievalResult, offset: int, limit: int,
               job_out: Callable[[Job], dict]) -> list[dict]:
    """One page of the ranked list in the keyword endpoint's shape (no score: only the order is meaningful)."""
    page = result.ranked[offset:offset + limit]
    jobs = {str(job.id): job for job in db.scalars(select(Job).where(Job.id.in_([row.job_id for row in page])))}
    return [{"job": job_out(jobs[row.job_id]), "score": None, "rank": row.rank, "reasons": list(row.reasons),
             "role_check": row.role, "seniority_check": row.seniority, "review": None}
            for row in page if row.job_id in jobs]
