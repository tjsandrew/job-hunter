"""Deterministic, versioned embedding text for a job.

Turns the job fields a teammate already has into one short text for the embedder.
Everything is nullable except the title. Location, work mode, status, salary and
the company name are deliberately *not* part of the text: they are filters or
display fields, and the company name would pull same-employer jobs together.

Three versions exist (``build_job_text(job, version=...)``):

* ``job-v2`` (the default): ``Role``, ``Stated skills`` (when the source has them) and the
  whole normalised description. No heading detection, so nothing can be silently dropped.
* ``job-v1``: keeps only the sections under known duties/requirements headings and drops known
  boilerplate; falls back to the whole description when no section is found or the extraction is
  too small. Frozen as first built, so results stay reproducible.
* ``job-v3``: ``job-v1`` made tolerant of headings with missing spaces ("Whatyou'll do") and with a
  stricter fallback (both Work and Requirements must be found, else the whole description).
  Exploratory: to be compared against ``job-v2`` once a larger, more varied job set exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

JOB_TEXT_VERSION = "job-v2"           # default format: Role, Stated skills, whole description
SECTIONS_TEXT_VERSION = "job-v1"      # heading-based extraction, as first built (frozen)
TOLERANT_SECTIONS_TEXT_VERSION = "job-v3"   # heading-based extraction, tolerant and stricter fallback
KNOWN_TEXT_VERSIONS = (JOB_TEXT_VERSION, SECTIONS_TEXT_VERSION, TOLERANT_SECTIONS_TEXT_VERSION)
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


def _squash(label: str) -> str:
    return label.replace(" ", "")


_SQUASHED_WORK = frozenset(_squash(h) for h in _WORK_HEADINGS)
_SQUASHED_REQUIREMENTS = frozenset(_squash(h) for h in _REQUIREMENT_HEADINGS)
_SQUASHED_EXCLUDED = frozenset(_squash(h) for h in _EXCLUDED_HEADINGS)
_RUN_TOGETHER_EXCLUDED_RE = re.compile(r"^(about|why)[A-Z]")      # "AboutStripe", "WhyJoin"


def _classify(line: str, tolerant: bool = False) -> str | None:
    """Return "work", "requirements", "excluded" or None when the line is not a known heading.

    ``tolerant`` also accepts headings whose spaces were lost in the source ("Whatyou'll do")."""
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
    if tolerant:
        squashed = _squash(label)
        if squashed in _SQUASHED_WORK:
            return "work"
        if squashed in _SQUASHED_REQUIREMENTS:
            return "requirements"
        if squashed in _SQUASHED_EXCLUDED or _RUN_TOGETHER_EXCLUDED_RE.match(line.strip()):
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


def _extract_sections(description: str, tolerant: bool = False) -> tuple[str, str]:
    """Return (work, requirements) text from known headings, or ("", "") when none apply."""
    work: list[str] = []
    requirements: list[str] = []
    current: str | None = None
    found = False
    for raw in _lines(description):
        kind = _classify(raw, tolerant)
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


@dataclass(frozen=True)
class SectionStats:
    """How heading detection did on one description (for judging a new source; not used to build text)."""

    total_chars: int
    work_chars: int
    requirements_chars: int
    used_sections: bool          # extraction would be trusted
    fallback_reason: str | None  # why the whole description would be used instead

    @property
    def kept_share(self) -> float:
        return (self.work_chars + self.requirements_chars) / self.total_chars if self.total_chars else 0.0


def section_stats(description: str | None, tolerant: bool = False) -> SectionStats:
    """Run heading detection on a description and report what it found."""
    text = description or ""
    full = _full_description(text) if text.strip() else ""
    if not full:
        return SectionStats(0, 0, 0, False, "no description")
    work, requirements = _extract_sections(text, tolerant)
    kept = len(work) + len(requirements)
    if kept < MIN_EXTRACTED_CHARS:
        reason = "no recognisable heading" if kept == 0 else "extracted text too small"
        return SectionStats(len(full), len(work), len(requirements), False, reason)
    if tolerant and not (work and requirements):
        return SectionStats(len(full), len(work), len(requirements), False,
                            "work section missing" if not work else "requirements section missing")
    return SectionStats(len(full), len(work), len(requirements), True, None)


def _labelled_text(labelled: list[tuple[str, str]], version: str, used_sections: bool) -> JobText:
    text = "\n".join(f"{label}: {value}" for label, value in labelled)
    truncated = len(text) > MAX_TEXT_CHARS
    if truncated:
        text = text[:MAX_TEXT_CHARS].rsplit(" ", 1)[0]
    return JobText(text=text, version=version, included=tuple(label for label, _ in labelled),
                   used_sections=used_sections, truncated=truncated)


def build_job_text(job: JobTextInput, version: str = JOB_TEXT_VERSION) -> JobText:
    """Assemble the versioned embedding text. Raises ``ValueError`` for a blank title or unknown version."""
    if version not in KNOWN_TEXT_VERSIONS:
        raise ValueError(f"unknown job text version {version!r}")
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
        if version == JOB_TEXT_VERSION:
            full = _full_description(description)
            if full:
                labelled.append(("Description", full))
        else:
            tolerant = version == TOLERANT_SECTIONS_TEXT_VERSION
            if section_stats(description, tolerant).used_sections:
                work, requirements = _extract_sections(description, tolerant)
                used_sections = True
                if work:
                    labelled.append(("Work", work))
                if requirements:
                    labelled.append(("Requirements", requirements))
            else:
                full = _full_description(description)
                if full:
                    labelled.append(("Description", full))
    return _labelled_text(labelled, version, used_sections)
