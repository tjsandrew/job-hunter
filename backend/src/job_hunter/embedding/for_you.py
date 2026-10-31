"""Semantic "for you" recommendations for one user, with a reason when it cannot be used.

``semantic_for_you`` returns ``(result, reason)``. ``result`` is ``None`` (and ``reason`` says why) whenever the
caller should fall back to the keyword ranker: no confirmed profile, or no profile vector yet. A profile vector
from a different model than every job vector also yields an empty result, never a mixed comparison.

``matching`` applies the same typed-search filter the keyword endpoint uses, and ``page_items`` turns one page of
ranked jobs into the keyword endpoint's item shape, with reasons a user can read (matched skills first, then the
role and level checks that actually matched; caveats such as "level not stated" are not reasons).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Iterable, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_hunter.domain.models import Job

from .db_retrieval import recommend_for_profile
from .features import FEATURES_VERSION
from .job_text import JOB_TEXT_VERSION
from .profile_text import PROFILE_TEXT_VERSION
from .retrieval import FUSION_VERSION, RankedJob, RetrievalResult, fuse_rankings

RANKING_VERSION = f"semantic:{JOB_TEXT_VERSION}+{PROFILE_TEXT_VERSION}+{FEATURES_VERSION}"
FUSED_RANKING_VERSION = f"{RANKING_VERSION}+{FUSION_VERSION}"
SEMANTIC_STATUS = "Semantic similarity after role and level checks; the order is meaningful, not the scores"
FUSED_STATUS = "Keyword and semantic matching combined after role and level checks; the order is meaningful, not the scores"
NO_PROFILE = "No confirmed profile yet, so the keyword ranker was used."
NO_VECTOR = ("We're still preparing your matches. This usually takes under a minute after you update your profile, "
             "so you're seeing all jobs for now. Refresh in a moment.")
SEARCH_FIELDS = ("title", "company", "description", "location", "category", "skills")
SIMILARITY_REASON = "Close to the experience in your profile"
MAX_SKILLS_SHOWN = 3


def semantic_for_you(db: Session, confirmed: "tuple[str, int, Any] | None", preferences: Mapping[str, Any] | None,
                     exclude_job_ids: Iterable[str] = (), posted_after: datetime | None = None,
                     include_closed: bool = False) -> "tuple[RetrievalResult | None, str | None]":
    """``confirmed`` is ``(profile_version_id, revision, snapshot)`` or ``None``; ``posted_after`` is Discover's "Posted" filter."""
    if confirmed is None:
        return None, NO_PROFILE
    result = recommend_for_profile(db, confirmed[0], preferences or {}, limit=None, exclude_job_ids=exclude_job_ids,
                                   posted_after=posted_after, include_closed=include_closed)
    if result is None:
        return None, NO_VECTOR
    return result, None


def fuse_with_keyword(ranked: Sequence[RankedJob], keyword_ranked: Sequence[Mapping[str, Any]]) -> tuple[RankedJob, ...]:
    """Merge the keyword ranker's output (``rank_jobs`` rows, best first) into the checked semantic ranking."""
    return fuse_rankings(ranked, [str(row["job"]["id"]) for row in keyword_ranked])


def _load_jobs(db: Session, job_ids: Sequence[str]) -> dict[str, Job]:
    if not job_ids:
        return {}
    return {str(job.id): job for job in db.scalars(select(Job).where(Job.id.in_(list(job_ids))))}


def matching(db: Session, ranked: Sequence[RankedJob], query: str | None,
             job_out: Callable[[Job], dict]) -> list[RankedJob]:
    """Keep the ranked jobs whose text contains ``query`` (case-insensitive), in the same order."""
    needle = (query or "").strip().casefold()
    if not needle:
        return list(ranked)
    jobs = _load_jobs(db, [row.job_id for row in ranked])
    kept = []
    for row in ranked:
        job = jobs.get(row.job_id)
        if job is None:
            continue
        fields = job_out(job)
        if needle in " ".join(str(fields.get(field) or "") for field in SEARCH_FIELDS).casefold():
            kept.append(row)
    return kept


def _skill_reason(snapshot: Mapping[str, Any] | None, preferences: Mapping[str, Any] | None,
                  job_fields: Mapping[str, Any]) -> str | None:
    """"Python, SQL appear in the listing": the profile skills the listing actually mentions."""
    try:   # reuses the keyword ranker's skill matching so a skill means the same thing in both places
        from job_hunter.recommendations import _find_skill_evidence, _profile_parts

        _, skills, _ = _profile_parts(snapshot or {}, preferences or {})
        names: list[str] = []
        for hit in _find_skill_evidence(skills, job_fields):
            if hit["skill"] not in names:
                names.append(hit["skill"])
    except Exception:   # the reason is a nicety; never let it break the list
        return None
    if not names:
        return None
    shown = ", ".join(names[:MAX_SKILLS_SHOWN])
    return f"{shown} {'appears' if len(names[:MAX_SKILLS_SHOWN]) == 1 else 'appear'} in the listing"


def page_items(db: Session, ranked: Sequence[RankedJob], offset: int, limit: int, job_out: Callable[[Job], dict], *,
               snapshot: Mapping[str, Any] | None = None, preferences: Mapping[str, Any] | None = None) -> list[dict]:
    """One page of ranked jobs in the keyword endpoint's shape (no score: only the order is meaningful)."""
    page = list(ranked[offset:offset + limit])
    jobs = _load_jobs(db, [row.job_id for row in page])
    items = []
    for row in page:
        job = jobs.get(row.job_id)
        if job is None:
            continue
        fields = job_out(job)
        reasons = [reason for reason in (_skill_reason(snapshot, preferences, fields), *row.reasons) if reason]
        items.append({"job": fields, "score": None, "rank": row.rank, "reasons": reasons or [SIMILARITY_REASON],
                      "role_check": row.role, "seniority_check": row.seniority, "review": None})
    return items
