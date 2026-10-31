"""Semantic candidate retrieval: eligibility first, then the role/seniority checks, then similarity.

Order matters. Hard filters and the checks run *before* ranking, so the top results are never
"the nearest jobs minus the ones we then had to throw away":

  1. **Eligibility** (open status, location, work mode, minimum salary, optional exclusions): the same rules the
     existing ranker applies, reusing its own helpers.
  2. **Checks**: a job whose role family is clearly different from the profile's, or whose level is
     two or more steps away, is blocked. Unknown values never block. Blocked jobs are returned in a
     separate list (with their similarity) so evaluation can see what was removed.
  3. **Similarity**: the remaining jobs are ranked by cosine similarity to the profile vector. Only
     the order is meaningful; the raw number is not a "match percentage".

Everything here is pure and in memory. ``db_retrieval.py`` loads candidates from the database.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping, Sequence

from .features import check_engineering_subrole, check_role_family, check_seniority

# The ranker's own eligibility helpers (private there). A test pins ``is_eligible`` to the exact set of
# jobs ``rank_jobs`` returns, so any drift is caught.
from job_hunter.recommendations import _as_locations, _location_matches, _salary_matches, _work_mode_matches


@dataclass(frozen=True)
class ProfileQuery:
    vector: Sequence[float]
    role_families: Sequence[str] = ()
    seniority_levels: Sequence[str] = ()
    engineering_subroles: Sequence[str] = ()


@dataclass(frozen=True)
class RetrievalCandidate:
    job_id: str
    vector: Sequence[float]
    role_family: str | None = None
    seniority_levels: Sequence[str] = ()
    engineering_subrole: str | None = None


@dataclass(frozen=True)
class RankedJob:
    job_id: str
    rank: int                  # 1-based position in the result
    similarity: float          # cosine similarity; only the ordering is meaningful
    role: str                  # same | adjacent | different | unknown
    seniority: str             # match | adjacent | mismatch | all_levels | unknown
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class BlockedJob:
    job_id: str
    similarity: float
    role: str
    seniority: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalResult:
    ranked: tuple[RankedJob, ...]
    blocked: tuple[BlockedJob, ...]   # removed by the checks, highest similarity first
    considered: int                   # candidates that reached the checks


def is_eligible(job: Mapping[str, Any], preferences: Mapping[str, Any] | None, include_closed: bool = False) -> bool:
    """Same eligibility the existing ranker applies: open (unless ``include_closed``), wanted location, wanted work mode,
    minimum salary."""
    preferences = preferences or {}
    if not include_closed and str(job.get("status", "open")).casefold() != "open":
        return False
    if not _location_matches(job.get("location"), _as_locations(preferences)):
        return False
    return _work_mode_matches(job, preferences) and _salary_matches(job, preferences)


def eligible_jobs(jobs: Iterable[Mapping[str, Any]], preferences: Mapping[str, Any] | None,
                  exclude_job_ids: Iterable[str] = (), include_closed: bool = False) -> list[Mapping[str, Any]]:
    excluded = {str(i) for i in exclude_job_ids}
    return [job for job in jobs if str(job.get("id")) not in excluded and is_eligible(job, preferences, include_closed)]


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("vectors must have the same number of dimensions")
    dot = sum(a * b for a, b in zip(left, right))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0


# Reasons are things worth telling a user about *why a job fits*. Caveats about what could not be checked
# (role type unknown, level not stated, seniority not set) are not reasons: the check verdicts are returned
# alongside (`role`, `seniority`) for anything that wants to show them as hints.
_ROLE_REASONS = {
    "same": "Same kind of role as your target role",
    "adjacent": "A related kind of role to your target role",
}
_LEVEL_REASONS = {
    "match": "Level matches your profile",
    "adjacent": "Level is close to your profile",
}


def _reasons(role: str, seniority: str) -> tuple[str, ...]:
    return tuple(text for text in (_ROLE_REASONS.get(role), _LEVEL_REASONS.get(seniority)) if text)


def retrieve(query: ProfileQuery, candidates: Iterable[RetrievalCandidate], *, limit: int | None = 10,
             apply_checks: bool = True) -> RetrievalResult:
    """Apply the checks, then rank the survivors by similarity.

    ``candidates`` must already be eligible (see :func:`eligible_jobs`). ``apply_checks=False``
    skips the blocking (checks are still reported) and exists to measure what the checks add.
    """
    ranked_rows: list[tuple[float, str, str, str, tuple[str, ...]]] = []
    blocked: list[BlockedJob] = []
    considered = 0
    for candidate in candidates:
        considered += 1
        similarity = cosine(query.vector, candidate.vector)
        role = check_role_family(candidate.role_family, query.role_families)
        subrole = check_engineering_subrole(candidate.role_family, candidate.engineering_subrole, query.role_families,
                                            query.engineering_subroles)
        if subrole.blocks:   # a clearly different kind of engineering job (support vs backend, frontend vs backend, ...)
            role = subrole
        level = check_seniority(candidate.seniority_levels, query.seniority_levels)
        reasons = _reasons(role.verdict, level.verdict)
        if apply_checks and (role.blocks or level.blocks):
            blocked_reasons = tuple(r.reason for r in (role, level) if r.blocks)
            blocked.append(BlockedJob(candidate.job_id, similarity, role.verdict, level.verdict, blocked_reasons))
            continue
        ranked_rows.append((similarity, candidate.job_id, role.verdict, level.verdict, reasons))

    ranked_rows.sort(key=lambda row: (-row[0], row[1]))          # stable, deterministic on ties
    if limit is not None:
        ranked_rows = ranked_rows[:limit]
    ranked = tuple(RankedJob(job_id=row[1], rank=position, similarity=row[0], role=row[2], seniority=row[3],
                             reasons=row[4]) for position, row in enumerate(ranked_rows, start=1))
    blocked.sort(key=lambda item: (-item.similarity, item.job_id))
    return RetrievalResult(ranked=ranked, blocked=tuple(blocked), considered=considered)


FUSION_VERSION = "rrf-v1"
FUSION_K = 60   # the constant from the original reciprocal-rank-fusion paper; deliberately not tuned on our data


def fuse_rankings(ranked: Sequence[RankedJob], keyword_order: Sequence[str], k: int = FUSION_K) -> tuple[RankedJob, ...]:
    """Reciprocal-rank fusion of the semantic ranking with the keyword ranking, over the jobs that passed the checks.

    ``ranked`` is the checked, similarity-ordered result of :func:`retrieve`; ``keyword_order`` is the keyword ranker's job
    ids, best first. Only jobs already in ``ranked`` can appear, so the checks still decide who is eligible: fusion changes
    the order, never the membership. Each job scores 1/(k+semantic position) + 1/(k+keyword position among those jobs); a job
    the keyword ranker did not list gets only the semantic term. Ties keep the semantic order. Check verdicts and reasons are
    kept; ranks are renumbered 1..n.
    """
    semantic_position = {row.job_id: i for i, row in enumerate(ranked, start=1)}
    keyword_position: dict[str, int] = {}
    for job_id in keyword_order:
        if job_id in semantic_position and job_id not in keyword_position:
            keyword_position[job_id] = len(keyword_position) + 1
    def score(row: RankedJob) -> float:
        total = 1.0 / (k + semantic_position[row.job_id])
        if row.job_id in keyword_position:
            total += 1.0 / (k + keyword_position[row.job_id])
        return total
    ordered = sorted(ranked, key=lambda row: (-score(row), semantic_position[row.job_id]))
    return tuple(replace(row, rank=position) for position, row in enumerate(ordered, start=1))
