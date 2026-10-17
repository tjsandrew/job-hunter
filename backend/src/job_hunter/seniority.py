"""Job title -> seniority levels: the one classifier for ingestion and for the recommender.

Ingestion calls ``classify_seniority`` (in ``import_jobs.py``) to fill ``jobs.seniority``,
``jobs.seniority_source`` and ``jobs.seniority_evidence``, the same way it fills ``jobs.category`` from
``job_hunter.role_family``. The recommender reads those columns, so there is one classifier and one stored
value. The profile side (a user's stated level) uses ``levels_from_text`` / ``normalise_levels`` from here too.

This is the single swap point if the deterministic rules are ever replaced (for example by an LLM that returns
both the level and the role family at ingestion): keep the return shape and the five-step ladder.

The ladder is intern < entry < mid < senior < lead. A job that names no level is stored as an empty list and
counts as open to every level; ``NULL`` means "not classified yet". "associate" and "manager" are deliberately
not read as levels: they say little about seniority ("Product Manager", "Customer Associate").
"""

from __future__ import annotations

import re
from typing import Sequence

SENIORITY_VERSION = "seniority-v1"      # stored as seniority_source when the levels come from the title
SENIORITY_STATED = "stated"            # stored as seniority_source when the job source named the level itself
EVIDENCE_MAX = 120                     # jobs.seniority_evidence is varchar(120)

SENIORITY_LADDER: tuple[str, ...] = ("intern", "entry", "mid", "senior", "lead")
SENIORITY_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "intern", "label": "Intern"},
    {"value": "entry", "label": "Junior / Entry-level"},
    {"value": "mid", "label": "Mid-level"},
    {"value": "senior", "label": "Senior"},
    {"value": "lead", "label": "Lead / Executive"},
)

# Ordered keyword patterns, one per ladder level.
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

# Plain words that only make sense as a *stated* level (a preference or a structured field), never as a
# title keyword: "Account Executive" is a sales job, not an executive-level one.
_STATED_ONLY_LEVELS = {"executive": "lead"}


def _matches(text: str | None) -> list[tuple[str, str]]:
    """(level, matched phrase) for every ladder level named in the text, in ladder order."""
    if not text:
        return []
    found = []
    for level, pattern in _SENIORITY_PATTERNS:
        hit = pattern.search(text)
        if hit:
            found.append((level, hit.group(0).strip()))
    return found


def levels_from_text(text: str | None) -> tuple[str, ...]:
    """Seniority levels named in a title or preference string, in ladder order."""
    return tuple(level for level, _ in _matches(text))


def normalise_levels(levels: str | Sequence[str] | None) -> tuple[str, ...]:
    """Accept ladder names ("entry") or plain wording ("Junior"); ignore anything else."""
    valid: set[str] = set()
    for level in ([levels] if isinstance(levels, str) else levels or ()):
        text = str(level).strip().lower()
        if text in SENIORITY_LADDER:
            valid.add(text)
        elif text in _STATED_ONLY_LEVELS:
            valid.add(_STATED_ONLY_LEVELS[text])
        else:
            valid.update(levels_from_text(text))
    return tuple(level for level in SENIORITY_LADDER if level in valid)


def classify_seniority(title: str | None, stated: str | Sequence[str] | None = None) -> "tuple[list[str], str, str | None]":
    """Return ``(levels, source, evidence)`` for one job.

    ``stated`` is a level the job source itself gives (a structured field), which beats the title. Otherwise the
    levels are read from the title. No level found gives an empty list: the job is open to every level.
    """
    given = normalise_levels(stated)
    if given:
        stated_values = [stated] if isinstance(stated, str) else stated or ()
        return list(given), SENIORITY_STATED, ", ".join(str(item) for item in stated_values)[:EVIDENCE_MAX] or None
    found = _matches(title)
    evidence = ", ".join(phrase for _, phrase in found)[:EVIDENCE_MAX] or None
    return [level for level, _ in found], SENIORITY_VERSION, evidence
