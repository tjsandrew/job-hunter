"""Job title -> seniority levels: the one classifier for ingestion and for the recommender.

Ingestion calls ``classify_seniority`` (in ``import_jobs.py``) to fill ``jobs.seniority``,
``jobs.seniority_source`` and ``jobs.seniority_evidence``, the same way it fills ``jobs.category`` from
``job_hunter.role_family``. The recommender reads those columns, so there is one classifier and one stored
value. The profile side (a user's stated level) uses ``levels_from_text`` / ``normalise_levels`` from here too.

This is the single swap point if the deterministic rules are ever replaced (for example by an LLM that returns
both the level and the role family at ingestion): keep the return shape and the ladder keys.

The contract has six levels: intern < junior < mid < senior < lead < executive (the words the preferences
dropdown always used). For the match checks ``lead`` and ``executive`` are the same step (``CHECK_LADDER``), because
the evidence so far is too small to say the split helps; split them there if a larger labelled set shows it does.
The title rules cannot tell the two apart yet, so they return ``lead`` for director/VP/chief/head-of titles;
``executive`` is stored only when a job source or a user states it. A job that names no level is stored as an empty
list and counts as open to every level; ``NULL`` means "not classified yet". "associate" and "manager" are
deliberately not read as levels: they say little about seniority ("Product Manager", "Customer Associate").
"""

from __future__ import annotations

import re
from typing import Sequence

SENIORITY_VERSION = "seniority-v1"      # stored as seniority_source when the levels come from the title
SENIORITY_STATED = "stated"            # stored as seniority_source when the job source named the level itself
EVIDENCE_MAX = 120                     # jobs.seniority_evidence is varchar(120)

SENIORITY_LADDER: tuple[str, ...] = ("intern", "junior", "mid", "senior", "lead", "executive")
SENIORITY_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "intern", "label": "Intern"},
    {"value": "junior", "label": "Junior / Entry-level"},
    {"value": "mid", "label": "Mid-level"},
    {"value": "senior", "label": "Senior"},
    {"value": "lead", "label": "Lead"},
    {"value": "executive", "label": "Executive"},
)

# What the match checks compare. Levels in the same group are one step apart from the rest of the ladder, so a
# lead job and an executive profile (or the reverse) count as the same level for now.
_CHECK_GROUP = {"executive": "lead"}
CHECK_LADDER: tuple[str, ...] = tuple(level for level in SENIORITY_LADDER if level not in _CHECK_GROUP)

# Keys and wording stored before this contract, accepted and converted when read.
_LEGACY_KEYS = {"entry": "junior", "mid-level": "mid"}

# Ordered keyword patterns, one per ladder level.
_SENIORITY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("intern", re.compile(r"\b(intern|internship|co-?op)\b", re.I)),
    ("junior", re.compile(r"\b(junior|jr|entry[\s-]*level|new[\s-]*grad(uate)?|graduate|early[\s-]*career|trainee)\b", re.I)),
    ("mid", re.compile(r"\b(mid[\s-]*level|intermediate)\b", re.I)),
    ("senior", re.compile(r"\b(senior|sr)\b", re.I)),
    ("lead", re.compile(
        r"\b(principal|distinguished|director|vp|vice[\s-]*president|chief|head[\s-]+of)\b"
        # Added 2026-10-16 after the head-to-head showed "Engineering Manager" roles (people management)
        # reaching junior profiles. Other "manager" titles are still not read as a level.
        r"|\bengineering\s+manager\b|\bmanager,\s*engineering\b"
        r"|^\s*head\b"  # "Head, Merchant Acquisition": the head-of-function form without "of"
        r"|\bstaff\s+(?:\w+\s+){0,2}(engineer|developer|scientist|designer|architect)\b"
        r"|\blead\b(?!\s*gen)", re.I)),
)

# "executive" is a *stated* level only (a preference or a structured field), never a title keyword:
# "Account Executive" is a sales job, not an executive-level one. It is not in _SENIORITY_PATTERNS for that reason.


def check_rank(level: str) -> int:
    """Position of a level on the ladder the match checks use (``executive`` shares ``lead``'s position)."""
    return CHECK_LADDER.index(_CHECK_GROUP.get(level, level))


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
    """Accept ladder keys ("junior"), plain wording ("Junior") or a legacy key ("entry"); ignore anything else."""
    valid: set[str] = set()
    for level in ([levels] if isinstance(levels, str) else levels or ()):
        text = str(level).strip().lower()
        if text in SENIORITY_LADDER:
            valid.add(text)
        elif text in _LEGACY_KEYS:
            valid.add(_LEGACY_KEYS[text])
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
