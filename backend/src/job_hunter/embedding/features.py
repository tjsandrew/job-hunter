"""Match features kept *outside* the embedding vector, and the checks that use them.

Embeddings find jobs that read alike; they cannot enforce "different occupation" or
"wrong experience level" (a recruiter or a principal-level job can read very close to a
junior backend profile). These small, transparent rules cover that gap:

* **Seniority** - a ladder of six levels (intern, junior, mid, senior, lead, executive) in which lead and
  executive count as one step for now (``job_hunter.seniority.CHECK_LADDER``). A job's levels are classified at
  ingestion (``job_hunter.seniority``) and stored in ``jobs.seniority``; a job that names no level counts as
  open to all levels (and is flagged as such, so evaluation can see how often the check did nothing). A
  profile's level comes from the user's preferences.
* **Role family** - the shared title classifier (``job_hunter.role_family``). Ingestion fills
  ``jobs.category`` with it and the recommender reads that column; a profile's target roles are classified with
  the same function. "other" is unknown, which counts as compatible.

Every check returns a verdict plus a reason; ``blocks`` is True only for a clear
mismatch. Unknown never blocks. Years-of-experience inference is deliberately not part
of this first version: mapping "N+ years" to a level is too error-prone to guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from job_hunter.role_family import CLASSIFIER_VERSION, ROLE_FAMILIES, classify_role_family
from job_hunter.seniority import SENIORITY_LADDER, check_rank, levels_from_text, normalise_levels

FEATURES_VERSION = "features-v3"   # part of the ranking version string, so a change to the rules is visible later

Classifier = Callable[[str], "tuple[str, str, str | None]"]


@dataclass(frozen=True)
class SeniorityCheck:
    verdict: str            # match | adjacent | mismatch | all_levels | unknown
    job_unspecified: bool   # True when the job named no level (counts as all levels)
    reason: str

    @property
    def blocks(self) -> bool:
        return self.verdict == "mismatch"


@dataclass(frozen=True)
class RoleCheck:
    verdict: str            # same | adjacent | different | unknown
    reason: str

    @property
    def blocks(self) -> bool:
        return self.verdict == "different"


@dataclass(frozen=True)
class ProfileFeatures:
    seniority_levels: tuple[str, ...]   # empty means not set
    role_families: tuple[str, ...]      # empty means unknown


def _default_classifier(title: str) -> "tuple[str, str, str | None]":
    family, evidence = classify_role_family(title)
    return family, CLASSIFIER_VERSION, evidence


def _family(category: str | None) -> str | None:
    value = (category or "").strip().lower()
    return value if value and value != "other" else None


def job_role_family(category: str | None) -> str | None:
    """The role family stored in ``jobs.category``, or None (unknown) when it is empty, "other" or not a known label."""
    value = _family(category)
    return value if value in ROLE_FAMILIES else None


def job_seniority_levels(value: "Sequence[str] | None") -> tuple[str, ...]:
    """The levels stored in ``jobs.seniority`` that are on the ladder, in ladder order (empty = open to all levels)."""
    return normalise_levels(value)


def role_hint_from_snapshot(snapshot: "dict | None") -> list[str]:
    """Role titles to use for the role check when the user set no target roles: the headline, else the latest role."""
    snapshot = snapshot or {}
    headline = str(snapshot.get("headline") or "").strip()
    if headline:
        return [headline]
    for item in snapshot.get("experience") or ():
        title = str((item.get("role") or item.get("title") or "") if isinstance(item, dict) else "").strip()
        if title:
            return [title]
    return []


def extract_profile_features(
    target_roles: Sequence[str] | None,
    seniority_preference: str | Sequence[str] | None,
    classify: Classifier | None = None,
) -> ProfileFeatures:
    """Features for one profile, from the user's preferences."""
    if isinstance(seniority_preference, str) or seniority_preference is None:
        levels = levels_from_text(seniority_preference) or (
            normalise_levels([seniority_preference]) if seniority_preference else ())
    else:
        levels = normalise_levels(seniority_preference)
    families: list[str] = []
    for role in target_roles or ():
        family = _family((classify or _default_classifier)(str(role))[0])
        if family and family not in families:
            families.append(family)
    return ProfileFeatures(seniority_levels=levels, role_families=tuple(families))


def check_seniority(job_levels: Sequence[str] | None, profile_levels: Sequence[str] | None) -> SeniorityCheck:
    """Compare job and profile levels. Unspecified job counts as all levels (flagged)."""
    job = normalise_levels(job_levels)
    profile = normalise_levels(profile_levels)
    if not job:
        return SeniorityCheck("all_levels", True, "the job does not state a level; counted as open to all levels")
    if not profile:
        return SeniorityCheck("unknown", False, "the profile has no seniority set")
    distance = min(abs(check_rank(j) - check_rank(p)) for j in job for p in profile)
    if distance == 0:
        return SeniorityCheck("match", False, "job and profile name the same level")
    if distance == 1:
        return SeniorityCheck("adjacent", False, "job and profile are one level apart")
    return SeniorityCheck("mismatch", False, f"job level {'/'.join(job)} is {distance} levels from profile level {'/'.join(profile)}")


# Judgement calls, easy to edit: pairs of job families that are close enough to be a
# plausible move rather than a different occupation.
ADJACENT_FAMILIES: frozenset[frozenset[str]] = frozenset(frozenset(pair) for pair in (
    ("engineering", "data"), ("engineering", "product"), ("product", "design"), ("product", "data"),
    ("sales", "customer_success"), ("sales", "marketing"), ("marketing", "design"),
    # Added 2026-10-16 after the judged-pair replay: technical support engineers and technical
    # account managers sit across these two families (title-keyword rules file them apart).
    ("engineering", "customer_success"),
))


def check_role_family(job_family: str | None, profile_families: Sequence[str] | None) -> RoleCheck:
    """Compare the job's family with the profile's target-role families (best verdict wins)."""
    job = _family(job_family)
    profile = [f for f in (_family(f) for f in (profile_families or ())) if f]
    if job is None:
        return RoleCheck("unknown", "the job's role family is unknown")
    if not profile:
        return RoleCheck("unknown", "the profile's target role family is unknown")
    if job in profile:
        return RoleCheck("same", f"both are {job}")
    for family in profile:
        if frozenset((job, family)) in ADJACENT_FAMILIES:
            return RoleCheck("adjacent", f"{job} is adjacent to {family}")
    return RoleCheck("different", f"job is {job}; profile targets {', '.join(profile)}")
