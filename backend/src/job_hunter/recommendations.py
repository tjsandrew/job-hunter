"""Deterministic, explainable local job ranking (no model or network calls).

The public ``rank_jobs`` interface accepts plain mappings so callers can adapt
ORM/API records without coupling the ranking rules to persistence.
"""

from __future__ import annotations

from collections import Counter, OrderedDict
from datetime import datetime, timezone
import functools
import math
import re
import threading
from typing import Any, Iterable, Mapping, Sequence

RANKING_VERSION = "local_tfidf_hybrid_v1"
SCORE_LABEL = "relevance score (not probability)"

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[+#][a-z0-9+#]*)*", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d .()/-]{7,}\d(?!\w)")
_STOP_WORDS = frozenset(
    "a an and are as at be by for from in into is it of on or our that the their this to with will you your we "
    "age aged disability disabled ethnicity ethnic gender female male man woman women men nationality "
    "race religion sex sexual orientation married marital"
    .split()
)

# Aliases are exact skill spellings. SQL and NoSQL remain separate skills.
_SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "sql": ("sql", "structured query language"),
    "nosql": ("nosql", "no sql", "non relational database"),
    "python": ("python", "python3"),
    "javascript": ("javascript", "js"),
    "typescript": ("typescript", "ts"),
    "postgresql": ("postgresql", "postgres"),
    "machine learning": ("machine learning", "ml"),
    "natural language processing": ("natural language processing", "nlp"),
    "aws": ("aws", "amazon web services"),
    "gcp": ("gcp", "google cloud platform"),
    "azure": ("azure", "microsoft azure"),
    "excel": ("excel", "microsoft excel", "ms excel"),
    "power bi": ("power bi", "powerbi"),
    "tableau": ("tableau",),
    "spark": ("spark", "apache spark"),
    "pytorch": ("pytorch", "py torch"),
    "tensorflow": ("tensorflow", "tensor flow"),
}
_ALIAS_TO_CANONICAL = {
    alias: canonical
    for canonical, aliases in _SKILL_ALIASES.items()
    for alias in aliases
}


_PROFILE_TEXT_FIELDS = ("summary", "headline", "professional_summary", "about")
_PROFILE_SKILL_FIELDS = ("skills", "core_skills", "technical_skills")
_PROFILE_ROLE_FIELDS = ("target_roles", "desired_roles", "roles", "role_keywords")
def _normalise_phrase(value: str) -> str:
    return " ".join(_TOKEN_RE.findall(value.casefold()))


def _tokenize(value: str) -> list[str]:
    value = _EMAIL_RE.sub(" ", value)
    value = _PHONE_RE.sub(" ", value)
    return [token.casefold() for token in _TOKEN_RE.findall(value) if token.casefold() not in _STOP_WORDS]


def _as_items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, Iterable):
        return list(value)
    return [value]


def _label(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key in ("name", "label", "skill", "title", "role", "text"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _unique_labels(*values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in _as_items(value):
            text = _label(item)
            if text and _normalise_phrase(text) not in seen:
                result.append(text)
                seen.add(_normalise_phrase(text))
    return result


def _canonical_skill(value: str) -> str:
    normalized = _normalise_phrase(value)
    return _ALIAS_TO_CANONICAL.get(normalized, normalized)


def _profile_parts(profile: Mapping[str, Any], preferences: Mapping[str, Any]) -> tuple[str, list[str], list[str]]:
    pieces: list[str] = []
    for key in _PROFILE_TEXT_FIELDS:
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            pieces.append(value.strip())

    skills = _unique_labels(*(profile.get(key) for key in _PROFILE_SKILL_FIELDS))
    roles = _unique_labels(
        *(profile.get(key) for key in _PROFILE_ROLE_FIELDS),
        preferences.get("roles"),
        preferences.get("target_roles"),
    )

    # Experience contributes role and skill facts only. Names/contact/protected
    # traits and arbitrary resume sections are never folded into the query.
    experience = profile.get("experience")
    for item in _as_items(experience):
        if isinstance(item, Mapping):
            role = item.get("title") or item.get("role")
            if isinstance(role, str) and role.strip():
                roles = _unique_labels(roles, role)
            exp_skills = _unique_labels(item.get("skills"))
            skills = _unique_labels(skills, exp_skills)

    # Also accept the common confirmed-profile wrapper while still selecting
    # only the explicit fields above.
    confirmed = profile.get("confirmed_facts")
    if isinstance(confirmed, Mapping):
        skills = _unique_labels(skills, *(confirmed.get(key) for key in _PROFILE_SKILL_FIELDS))
        roles = _unique_labels(roles, *(confirmed.get(key) for key in _PROFILE_ROLE_FIELDS))
        for key in _PROFILE_TEXT_FIELDS:
            value = confirmed.get(key)
            if isinstance(value, str) and value.strip():
                pieces.append(value.strip())

    return " ".join(pieces), skills, roles


def _job_skills(job: Mapping[str, Any]) -> list[str]:
    return _unique_labels(job.get("skills"), job.get("required_skills"), job.get("matched_skills"))


def _job_document(job: Mapping[str, Any]) -> str:
    parts = []
    for key in ("title", "description", "category", "department"):
        value = job.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    parts.extend(_job_skills(job))
    return " ".join(parts)


# Tokenising every open job's description is the biggest fixed cost of a ranking request, and a job's text only
# changes when a pull rewrites it. Counts are kept per document text (looked up by the text itself, so a changed
# description can never be served stale). The cache is per process, bounded, and the counts are never mutated.
_DOCUMENT_CACHE_SIZE = 8192   # two texts per job (ranking document, title + description): room for ~4,000 jobs
_document_cache: OrderedDict[str, Counter[str]] = OrderedDict()
_document_cache_lock = threading.Lock()


def _document_counts(document: str) -> Counter[str]:
    with _document_cache_lock:
        counts = _document_cache.get(document)
        if counts is not None:
            _document_cache.move_to_end(document)
            return counts
    counts = Counter(_tokenize(document))
    with _document_cache_lock:
        _document_cache[document] = counts
        while len(_document_cache) > _DOCUMENT_CACHE_SIZE:
            _document_cache.popitem(last=False)
    return counts


def _tfidf_vectors(query: str, documents: Sequence[str]) -> tuple[dict[str, float], list[dict[str, float]]]:
    query_counts = Counter(_tokenize(query))
    if not query_counts:
        return {}, [{} for _ in documents]
    document_counts = [_document_counts(doc) for doc in documents]
    document_frequency = Counter()
    for counts in document_counts:
        document_frequency.update(counts.keys())
    total_docs = max(1, len(documents))

    def weighted(counts: Counter[str]) -> dict[str, float]:
        vector = {}
        for term, count in counts.items():
            inverse = math.log((1 + total_docs) / (1 + document_frequency[term])) + 1.0
            vector[term] = (1.0 + math.log(count)) * inverse
        return vector

    return weighted(query_counts), [weighted(counts) for counts in document_counts]


def _cosine(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(value * right.get(term, 0.0) for term, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def _role_overlap(title: str, roles: Sequence[str]) -> tuple[float, list[str]]:
    title_terms = set(_tokenize(title))
    if not title_terms or not roles:
        return 0.0, []
    scores: list[tuple[float, str, list[str]]] = []
    for role in roles:
        role_terms = set(_tokenize(role))
        overlap = sorted(title_terms & role_terms)
        if not role_terms:
            continue
        exact_phrase = _normalise_phrase(role) in _normalise_phrase(title)
        score = 1.0 if exact_phrase else len(overlap) / len(title_terms | role_terms)
        scores.append((score, role, overlap))
    if not scores:
        return 0.0, []
    best_score, best_role, overlap = max(scores, key=lambda row: (row[0], row[1].casefold()))
    return best_score, [best_role] if best_score >= 0.25 else []


@functools.lru_cache(maxsize=2048)
def _alias_matcher(alias: str) -> tuple[re.Pattern[str], str | None]:
    """The whole-word pattern for a skill spelling, and its lower-case form when plain text can pre-check it."""
    pattern = re.compile(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", re.IGNORECASE)
    return pattern, alias.lower() if alias.isascii() else None


# The only non-ASCII characters that a case-insensitive pattern matches to an ASCII character are U+0130 "İ" (lower() gives
# "i" plus U+0307), U+0131 "ı", U+017F "ſ" (all three match "i" or "s") and the Kelvin sign (lower() already gives "k").
# Folding them this way makes the plain-text pre-check exact for any text, not only ASCII text; the regex still decides.
_ASCII_CASE_FIXES = (("\u0307", ""), ("\u0131", "i"), ("\u017f", "s"))


def _searchable_lower(text: str) -> str:
    """Lower-cased text in which an ASCII spelling appears whenever the case-insensitive whole-word pattern could match."""
    lowered = text.lower()
    if not text.isascii():
        for character, replacement in _ASCII_CASE_FIXES:   # str.replace is far faster than str.translate here
            if character in lowered:
                lowered = lowered.replace(character, replacement)
    return lowered


def _find_skill_evidence(profile_skills: Sequence[str], job: Mapping[str, Any]) -> list[dict[str, str]]:
    explicit = _job_skills(job)
    explicit_by_canonical = {_canonical_skill(skill): skill for skill in explicit}
    # A spelling that is not even a substring of the folded text cannot match the case-insensitive whole-word pattern,
    # so the (much slower) regex only runs on the few texts that mention it. ASCII spellings are pre-checked against any
    # text (see _searchable_lower); a non-ASCII spelling always goes to the regex.
    searchable_fields = []
    for key in ("title", "description"):
        value = job.get(key)
        if isinstance(value, str) and value:
            searchable_fields.append((key, value, _searchable_lower(value)))
    evidence: list[dict[str, str]] = []
    for user_skill in profile_skills:
        canonical = _canonical_skill(user_skill)
        if canonical in explicit_by_canonical:
            evidence.append({"skill": user_skill, "source": "job.skills", "matched_text": explicit_by_canonical[canonical]})
            continue
        aliases = _SKILL_ALIASES.get(canonical, (user_skill,))
        hit = None
        for field, field_text, field_lower in searchable_fields:
            for alias in aliases:
                pattern, alias_lower = _alias_matcher(alias)
                if alias_lower is not None and alias_lower not in field_lower:
                    continue
                match = pattern.search(field_text)
                if match:
                    hit = {"skill": user_skill, "source": field, "matched_text": match.group(0)}
                    break
            if hit:
                break
        if hit:
            evidence.append(hit)
    return evidence


def _as_locations(preferences: Mapping[str, Any]) -> list[str]:
    return _unique_labels(preferences.get("locations"), preferences.get("location"))


def _location_matches(job_location: Any, wanted_locations: Sequence[str]) -> bool:
    if not wanted_locations:
        return True
    if not isinstance(job_location, str) or not job_location.strip():
        return False
    normalized_job = _normalise_phrase(job_location)
    job_tokens = set(normalized_job.split())
    for wanted in wanted_locations:
        normalized_wanted = _normalise_phrase(wanted)
        if not normalized_wanted:
            continue
        if f" {normalized_wanted} " in f" {normalized_job} ":
            return True
        if normalized_wanted in {"sg", "sgp"} and "singapore" in job_tokens:
            return True
        if normalized_wanted == "singapore" and ({"sg", "sgp"} & job_tokens):
            return True
    return False


def _work_mode_matches(job: Mapping[str, Any], preferences: Mapping[str, Any]) -> bool:
    wanted = _unique_labels(preferences.get("work_modes"), preferences.get("work_mode"))
    if not wanted:
        return True
    actual = job.get("work_mode")
    if not isinstance(actual, str) or not actual.strip():
        return False
    actual_value = actual.casefold().replace("_", "-").strip()
    aliases = {"on-site": "onsite", "on site": "onsite", "wfh": "remote"}
    actual_value = aliases.get(actual_value, actual_value)
    return any(aliases.get(value.casefold().replace("_", "-").strip(), value.casefold()) == actual_value for value in wanted)


# Multipliers to a yearly figure. Boards spell periods differently ("year", "Monthly", "per_hour"); hourly assumes
# a 40-hour week, 52 weeks a year.
_PERIODS_PER_YEAR = {"year": 1, "month": 12, "week": 52, "day": 260, "hour": 2080}


def _per_year(period: Any) -> int | None:
    value = str(period or "").casefold()
    if "annual" in value or "year" in value:
        return 1
    return next((count for name, count in _PERIODS_PER_YEAR.items() if name in value), None)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _salary_matches(job: Mapping[str, Any], preferences: Mapping[str, Any]) -> bool:
    """The top of the job's stated range reaches the user's minimum salary.

    Only a salary that can be compared filters: a job with no salary, another currency, or a period that cannot be
    converted passes, so turning the filter on never hides most boards' listings.
    """
    wanted = _number(preferences.get("salary_min"))
    if wanted is None:
        return True
    offered = _number(job.get("salary_max")) or _number(job.get("salary_min"))
    if offered is None:
        return True
    wanted_currency = str(preferences.get("salary_currency") or "").strip().casefold()
    job_currency = str(job.get("salary_currency") or "").strip().casefold()
    if wanted_currency and job_currency and wanted_currency != job_currency:
        return True
    wanted_per_year = _per_year(preferences.get("salary_period") or "year")
    job_per_year = _per_year(job.get("salary_period"))
    if wanted_per_year is None or job_per_year is None:
        return True
    return offered * job_per_year >= wanted * wanted_per_year


def _posted_sort_key(job: Mapping[str, Any], index: int) -> tuple[float, str, int]:
    value = job.get("posted_at") or job.get("fetched_at")
    timestamp = 0.0
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            dt = None
    else:
        dt = None
    if dt is not None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        timestamp = dt.timestamp()
    identity = str(job.get("id") or job.get("dedup_key") or job.get("external_id") or "")
    return -timestamp, identity, index


def rank_jobs(
    jobs: Sequence[Mapping[str, Any]],
    profile: Mapping[str, Any] | None,
    preferences: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Rank eligible open jobs by local TF-IDF, explicit skills, and target roles.

    Scores are bounded numeric relevance values, not probabilities. Explicit
    location/work-mode preferences are hard filters. Missing location passes
    only when no location was selected; selected location + unknown job location
    is ineligible. A minimum salary filters only jobs whose salary can be
    compared (see ``_salary_matches``); unknown salary passes.

    Returned items contain the original job mapping and reproducible component
    scores, exact matched-skill evidence, reasons, and ranking version.
    """
    profile = profile or {}
    preferences = preferences or {}
    query_text, profile_skills, target_roles = _profile_parts(profile, preferences)
    skill_query = " ".join(profile_skills)
    role_query = " ".join(target_roles)
    query = " ".join(part for part in (query_text, skill_query, role_query) if part)
    wanted_locations = _as_locations(preferences)

    eligible: list[tuple[int, Mapping[str, Any]]] = []
    for index, job in enumerate(jobs):
        if str(job.get("status", "open")).casefold() != "open":
            continue
        if not _location_matches(job.get("location"), wanted_locations):
            continue
        if not _work_mode_matches(job, preferences):
            continue
        if not _salary_matches(job, preferences):
            continue
        eligible.append((index, job))

    documents = [_job_document(job) for _, job in eligible]
    query_vector, doc_vectors = _tfidf_vectors(query, documents)
    active_weights: dict[str, float] = {}
    if query_vector:
        active_weights["text_similarity"] = 0.50
    if profile_skills:
        active_weights["skill_overlap"] = 0.35
    if target_roles:
        active_weights["role_alignment"] = 0.15
    total_weight = sum(active_weights.values())
    cold_start = not active_weights
    query_terms = set(_tokenize(query))

    results = []
    for (original_index, job), document_vector in zip(eligible, doc_vectors):
        text_score = _cosine(query_vector, document_vector)
        skill_evidence = _find_skill_evidence(profile_skills, job)
        skill_score = len(skill_evidence) / len(profile_skills) if profile_skills else 0.0
        role_score, matched_roles = _role_overlap(str(job.get("title") or ""), target_roles)
        components = {
            "text_similarity": round(text_score, 6),
            "skill_overlap": round(skill_score, 6),
            "role_alignment": round(role_score, 6),
        }
        score = 0.0
        if total_weight:
            score = sum(components[key] * weight for key, weight in active_weights.items()) / total_weight
        score = round(score, 6)

        evidence: list[dict[str, Any]] = []
        for item in skill_evidence:
            evidence.append({
                "kind": "skill_match",
                "text": f"{item['skill']} appears in the listing",
                **item,
            })
        for role in matched_roles:
            evidence.append({
                "kind": "target_role",
                "text": f"The title aligns with target role {role}",
                "target_role": role,
            })
        if wanted_locations:
            evidence.append({
                "kind": "location_eligibility",
                "text": "The listing location matches a selected location",
                "job_location": job.get("location"),
                "selected_locations": wanted_locations,
            })
        has_relevance_evidence = any(item["kind"] in {"skill_match", "target_role", "term_overlap"} for item in evidence)
        if not has_relevance_evidence and not cold_start and text_score > 0:
            job_terms = _document_counts(" ".join((str(job.get("title") or ""), str(job.get("description") or ""))))
            overlap = sorted(query_terms & job_terms.keys())[:5]
            if overlap:
                evidence.append({"kind": "term_overlap", "text": "Shared listing terms: " + ", ".join(overlap), "terms": overlap})
        if cold_start:
            reason = "Add skills, a summary, or target roles to personalize recommendations."
        elif evidence:
            reason = "; ".join(item["text"] for item in evidence[:3])
        else:
            reason = "Ranked by overall title and description relevance."

        results.append({
            "job": job,
            "score": score,
            "score_label": SCORE_LABEL,
            "components": components,
            "reason": reason,
            "evidence": evidence,
            "matched_skills": [item["skill"] for item in skill_evidence],
            "ranking_version": RANKING_VERSION,
            "mode": "cold_start" if cold_start else "local_hybrid",
            "_tie": _posted_sort_key(job, original_index),
        })

    results.sort(key=lambda result: (-result["score"], result["_tie"]))
    for rank, result in enumerate(results, start=1):
        result["rank"] = rank
        del result["_tie"]
    return results
