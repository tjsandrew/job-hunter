"""Match features kept *outside* the embedding vector, and the checks that use them.

Embeddings find jobs that read alike; they cannot enforce "different occupation" or
"wrong experience level" (a recruiter or a principal-level job can read very close to a
junior backend profile). These small, transparent rules cover that gap:

* **Seniority** - a five-step ladder (intern, entry, mid, senior, lead). Job levels come
  from an explicit value when the caller has one, otherwise from conservative title
  keywords, otherwise the job is "unspecified" and counts as open to every level (and is
  flagged as such, so evaluation can see how often the check did nothing).
* **Role family** - reuses the job family the ingestion code already stores in
  ``jobs.category`` (``classify_title`` in ``import_jobs.py``). Jobs the classifier files
  under "other" are unknown, which counts as compatible.

Every check returns a verdict plus a reason; ``blocks`` is True only for a clear
mismatch. Unknown never blocks. Years-of-experience inference is deliberately not part
of this first version: mapping "N+ years" to a level is too error-prone to guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Sequence

FEATURES_VERSION = "features-v1"   # stored with the job features so a rule change is visible later

SENIORITY_LADDER: tuple[str, ...] = ("intern", "entry", "mid", "senior", "lead")

SOURCE_STATED = "stated"
SOURCE_INFERRED_FROM_TITLE = "inferred_from_title"
SOURCE_UNSPECIFIED = "unspecified"

# Ordered keyword patterns. "associate" and "manager" are deliberately absent: they say
# little about level ("Product Manager", "Customer Associate"), so we do not guess.
_SENIORITY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("intern", re.compile(r"\b(intern|internship|co-?op)\b", re.I)),
    ("entry", re.compile(r"\b(junior|jr|entry[\s-]*level|new[\s-]*grad(uate)?|graduate|early[\s-]*career|trainee)\b", re.I)),
    ("mid", re.compile(r"\b(mid[\s-]*level|intermediate)\b", re.I)),
    ("senior", re.compile(r"\b(senior|sr)\b", re.I)),
    ("lead", re.compile(
        r"\b(principal|distinguished|director|vp|vice[\s-]*president|chief|head[\s-]+of)\b"
        # Added 2026-10-16 after the head-to-head showed "Engineering Manager" roles (people management)
        # reaching junior profiles. Other "manager" titles are still not read as a level.
        r"|\bengineering\s+manager\b|\bmanager,\s*engineering\b"
        r"|\bstaff\s+(?:\w+\s+){0,2}(engineer|developer|scientist|designer|architect)\b"
        r"|\blead\b(?!\s*gen)", re.I)),
)

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
class JobFeatures:
    seniority_levels: tuple[str, ...]   # empty means unspecified
    seniority_source: str
    role_family: str | None             # None means unknown


@dataclass(frozen=True)
class ProfileFeatures:
    seniority_levels: tuple[str, ...]   # empty means not set
    role_families: tuple[str, ...]      # empty means unknown


def levels_from_text(text: str | None) -> tuple[str, ...]:
    """Seniority levels named in a title or preference string, in ladder order."""
    if not text:
        return ()
    found = [level for level, pattern in _SENIORITY_PATTERNS if pattern.search(text)]
    return tuple(found)


def _normalise_levels(levels: Sequence[str] | None) -> tuple[str, ...]:
    """Accept ladder names ("entry") or plain wording ("Junior"); ignore anything else."""
    valid: set[str] = set()
    for level in levels or ():
        text = str(level).strip().lower()
        if text in SENIORITY_LADDER:
            valid.add(text)
        else:
            valid.update(levels_from_text(text))
    return tuple(level for level in SENIORITY_LADDER if level in valid)


def _default_classifier(title: str) -> "tuple[str, str, str | None]":
    from job_hunter.import_jobs import classify_title  # lazy: that module needs SQLAlchemy

    return classify_title(title)


def _family(category: str | None) -> str | None:
    value = (category or "").strip().lower()
    return value if value and value != "other" else None


def extract_job_features(
    title: str,
    category: str | None = None,
    stated_seniority: Sequence[str] | None = None,
    classify: Classifier | None = None,
) -> JobFeatures:
    """Features for one job. ``category`` is the stored ``jobs.category`` when available."""
    stated = _normalise_levels(stated_seniority)
    if stated:
        levels, source = stated, SOURCE_STATED
    else:
        inferred = levels_from_text(title)
        levels, source = (inferred, SOURCE_INFERRED_FROM_TITLE) if inferred else ((), SOURCE_UNSPECIFIED)
    family = _family(category)
    if family is None and title:
        family = _family((classify or _default_classifier)(title)[0])
    return JobFeatures(seniority_levels=levels, seniority_source=source, role_family=family)


def extract_profile_features(
    target_roles: Sequence[str] | None,
    seniority_preference: str | Sequence[str] | None,
    classify: Classifier | None = None,
) -> ProfileFeatures:
    """Features for one profile, from the user's preferences."""
    if isinstance(seniority_preference, str) or seniority_preference is None:
        levels = levels_from_text(seniority_preference)
    else:
        levels = _normalise_levels(seniority_preference)
    families: list[str] = []
    for role in target_roles or ():
        family = _family((classify or _default_classifier)(str(role))[0])
        if family and family not in families:
            families.append(family)
    return ProfileFeatures(seniority_levels=levels, role_families=tuple(families))


def check_seniority(job_levels: Sequence[str] | None, profile_levels: Sequence[str] | None) -> SeniorityCheck:
    """Compare job and profile levels. Unspecified job counts as all levels (flagged)."""
    job = _normalise_levels(job_levels)
    profile = _normalise_levels(profile_levels)
    if not job:
        return SeniorityCheck("all_levels", True, "the job does not state a level; counted as open to all levels")
    if not profile:
        return SeniorityCheck("unknown", False, "the profile has no seniority set")
    distance = min(abs(SENIORITY_LADDER.index(j) - SENIORITY_LADDER.index(p)) for j in job for p in profile)
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
