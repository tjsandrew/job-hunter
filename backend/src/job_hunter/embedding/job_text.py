"""Deterministic, versioned embedding text for a job (version ``job-v1``).

Turns the job fields a teammate already has into one short text for the embedder.
Everything is nullable except the title. Location, work mode, status, salary and
the company name are deliberately *not* part of the text: they are filters or
display fields, and the company name would pull same-employer jobs together.

Description cleanup is conservative: only sections under known headings are kept
(duties and requirements) and known boilerplate sections are dropped. When the
description has no recognisable duties/requirements section, or the extraction is
too small to trust, the whole normalised description is used instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

JOB_TEXT_VERSION = "job-v1"
MAX_TEXT_CHARS = 8000          # safety cap well below the embedder's own limit
MIN_EXTRACTED_CHARS = 100      # below this, trust the full description instead

# Headings are compared after lower-casing and replacing every non-alphanumeric run
# with one space, so "What you'll do:" and the garbled "What you�ll do" both become
# "what you ll do".
_WORK_HEADINGS = frozenset({
    "about the role", "role summary", "job summary", "job brief", "the role", "role overview",
    "what you ll do", "what you will do", "what you ll be doing", "responsibilities",
    "key responsibilities", "your responsibilities", "duties", "key duties", "day to day",
    "in this role you will",
})
_REQUIREMENT_HEADINGS = frozenset({
    "who you are", "what you ll need", "what you will need", "what you bring", "what we seek",
    "what we re looking for", "who we are looking for", "you may be a fit for this role if",
    "requirements", "minimum requirements", "basic qualifications", "preferred requirements",
    "preferred qualifications", "qualifications", "required skills and experience",
    "required skills experience", "role specifications qualifications", "skills and experience",
    "nice to have", "bonus points",
})
_EXCLUDED_HEADINGS = frozenset({
    "about us", "who we are", "about the team", "our team", "our culture", "our values",
    "equal opportunity", "equal opportunity employer", "benefits", "perks", "compensation",
    "pay and benefits", "our benefits", "diversity and inclusion", "privacy policy",
    "application process", "how to apply", "how we hire", "office locations",
})
_EXCLUDED_PREFIXES = ("about ", "why ", "annual base salary", "salary range", "pay range",
                      "equal opportunity", "our benefits")
# "about the role" starts with "about " but is a duties heading, so it is checked first.

_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_HASHTAG_LINE_RE = re.compile(r"^#li-\w+$", re.IGNORECASE)
_BULLET_RE = re.compile(r"^[\s\-\*•·●▪–—�]+")


@dataclass(frozen=True)
class JobTextInput:
    """The job facts the text is built from. Only ``title`` is required."""

    title: str
    description: str | None = None
    skills: Sequence[str] | None = None

    @classmethod
    def from_job(cls, job: Any) -> "JobTextInput":
        """Build from a ``Job`` row, a dict-like record or any object with these attributes."""

        def get(name: str) -> Any:
            if isinstance(job, Mapping):
                return job.get(name)
            return getattr(job, name, None)

        skills = get("skills")
        return cls(title=get("title") or "", description=get("description"),
                   skills=list(skills) if skills else None)


@dataclass(frozen=True)
class JobText:
    text: str
    version: str
    included: tuple[str, ...]      # labels present, e.g. ("Role", "Work", "Requirements")
    used_sections: bool            # True when duties/requirements sections were extracted
    truncated: bool                # True when the safety cap shortened the text


def _normalise_heading(line: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", line.casefold()).strip()


def _classify(line: str) -> str | None:
    """Return "work", "requirements", "excluded" or None when the line is not a known heading."""
    if len(line) > 90:
        return None
    label = _normalise_heading(line)
    if not label:
        return None
    if label in _WORK_HEADINGS:
        return "work"
    if label in _REQUIREMENT_HEADINGS:
        return "requirements"
    if label in _EXCLUDED_HEADINGS or label.startswith(_EXCLUDED_PREFIXES):
        return "excluded"
    return None


def _repair_replacement_characters(line: str) -> str:
    """Defensive clean-up for text that arrived with U+FFFD ("we�re", "$1�$2").

    The 70 listings checked on 2026-10-16 did not contain any (their curly apostrophes are
    fine), but other sources or encodings can. Between letters it is treated as an
    apostrophe, between digits as a dash, and anywhere else it is dropped.
    """
    line = re.sub(r"(?<=[A-Za-z])�(?=[A-Za-z])", "'", line)
    line = re.sub(r"(?<=\d)�(?=\d)", "-", line)
    return line.replace("�", "")


def _clean_line(line: str) -> str:
    line = _BULLET_RE.sub("", line)
    line = _repair_replacement_characters(line)
    line = _URL_RE.sub("", line)
    line = _EMAIL_RE.sub("", line)
    return re.sub(r"\s+", " ", line).strip()


def _join(lines: Sequence[str]) -> str:
    """Join cleaned lines into one passage, ending each line with punctuation."""
    parts = []
    for line in lines:
        if line and line[-1] not in ".;:!?":
            line += "."
        parts.append(line)
    return " ".join(parts)


def _lines(description: str) -> list[str]:
    return [raw.strip() for raw in description.splitlines()
            if raw.strip() and not _HASHTAG_LINE_RE.match(raw.strip())]


def _extract_sections(description: str) -> tuple[str, str]:
    """Return (work, requirements) text from known headings, or ("", "") when none apply."""
    work: list[str] = []
    requirements: list[str] = []
    current: str | None = None
    found = False
    for raw in _lines(description):
        kind = _classify(raw)
        if kind is not None:
            current = kind if kind != "excluded" else None
            found = found or kind in ("work", "requirements")
            continue
        if current is None:
            continue
        cleaned = _clean_line(raw)
        if cleaned:
            (work if current == "work" else requirements).append(cleaned)
    if not found:
        return "", ""
    return _join(work), _join(requirements)


def _full_description(description: str) -> str:
    return _join([line for line in (_clean_line(raw) for raw in _lines(description)) if line])


def _skills_line(skills: Sequence[str] | None) -> str:
    seen: dict[str, str] = {}
    for skill in skills or ():
        text = re.sub(r"\s+", " ", str(skill)).strip()
        if text and text.casefold() not in seen:
            seen[text.casefold()] = text
    return ", ".join(seen.values())


def build_job_text(job: JobTextInput) -> JobText:
    """Assemble the versioned embedding text. Raises ``ValueError`` for a blank title."""
    title = re.sub(r"\s+", " ", job.title or "").strip()
    if not title:
        raise ValueError("a job title is required to build embedding text")

    labelled: list[tuple[str, str]] = [("Role", title)]
    skills = _skills_line(job.skills)
    if skills:
        labelled.append(("Stated skills", skills))

    used_sections = False
    description = job.description or ""
    if description.strip():
        work, requirements = _extract_sections(description)
        if len(work) + len(requirements) >= MIN_EXTRACTED_CHARS:
            used_sections = True
            if work:
                labelled.append(("Work", work))
            if requirements:
                labelled.append(("Requirements", requirements))
        else:
            full = _full_description(description)
            if full:
                labelled.append(("Description", full))

    text = "\n".join(f"{label}: {value}" for label, value in labelled)
    truncated = len(text) > MAX_TEXT_CHARS
    if truncated:
        text = text[:MAX_TEXT_CHARS].rsplit(" ", 1)[0]
    return JobText(
        text=text,
        version=JOB_TEXT_VERSION,
        included=tuple(label for label, _ in labelled),
        used_sections=used_sections,
        truncated=truncated,
    )
