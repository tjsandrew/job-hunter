"""Deterministic, versioned embedding text for a profile (version ``profile-v2``).

Built from the confirmed profile snapshot plus the user's target roles (which live
in preferences, not in the profile version). The older ``profile-v1`` text from
``profile_bank.snapshots.profile_embedding_text`` stays untouched as the baseline.

Differences from v1: a labelled layout that mirrors the job text, the target role
as its own line, and only facts the user confirmed (no education, no contact data).
Contact fields are removed by reusing the existing v1 stripping function, so the
privacy behaviour is identical.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from job_hunter.profile_bank.snapshots import profile_embedding_text as _contact_free_text

PROFILE_TEXT_VERSION = "profile-v2"
MAX_TEXT_CHARS = 8000

# Fields the v1 function treats as contact data. They are passed along only so that
# their values are scrubbed out of every piece of text we assemble.
_CONTACT_KEYS = ("name", "display_name", "email", "phone", "links", "location")
_PREFERENCE_ROLE_KEYS = ("target_roles", "roles")
_SPLIT_RE = re.compile(r"[;,\n]")


@dataclass(frozen=True)
class ProfileTextInput:
    """A confirmed profile snapshot and the user's target roles (nullable)."""

    snapshot: Mapping[str, Any]
    target_roles: Sequence[str] | None = None

    @classmethod
    def from_preferences(cls, snapshot: Mapping[str, Any], preferences: Mapping[str, Any] | None) -> "ProfileTextInput":
        """Read target roles from a preferences record, as the existing ranker does."""
        roles: list[str] = []
        for key in _PREFERENCE_ROLE_KEYS:
            roles.extend(_labels((preferences or {}).get(key)))
        return cls(snapshot=snapshot, target_roles=roles or None)


@dataclass(frozen=True)
class ProfileText:
    text: str
    version: str
    included: tuple[str, ...]      # labels present, e.g. ("Target role", "Summary", "Demonstrated skills")
    truncated: bool


def _labels(value: Any) -> list[str]:
    """Normalise a list of strings or a delimited string into clean, de-duplicated labels."""
    if value is None:
        return []
    raw = value if isinstance(value, (list, tuple, set)) else _SPLIT_RE.split(str(value))
    seen: dict[str, str] = {}
    for item in raw:
        text = re.sub(r"\s+", " ", str(item)).strip()
        if text and text.casefold() not in seen:
            seen[text.casefold()] = text
    return list(seen.values())


def _scrub(piece: str, snapshot: Mapping[str, Any]) -> str:
    """Remove contact details from one piece of text using the v1 stripping logic."""
    carrier = {key: snapshot.get(key) for key in _CONTACT_KEYS}
    carrier["summary"] = piece
    return " ".join(_contact_free_text(carrier).split())


def _sentence(text: str) -> str:
    text = text.strip()
    return text if not text or text[-1] in ".;:!?" else text + "."


def _entries(snapshot: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    value = snapshot.get(key)
    return [entry for entry in value if isinstance(entry, Mapping)] if isinstance(value, list) else []


def _bullet_texts(snapshot: Mapping[str, Any]) -> list[str]:
    """Achievement text: the flat bank list when present, else the per-entry legacy bullets."""
    flat = snapshot.get("bullets")
    texts: list[str] = []
    if isinstance(flat, list):
        for point in flat:
            texts.append(point.get("text", "") if isinstance(point, Mapping) else str(point))
    else:
        for key in ("experience", "projects"):
            for entry in _entries(snapshot, key):
                for point in entry.get("bullets") or []:
                    texts.append(point.get("text", "") if isinstance(point, Mapping) else str(point))
    return [t for t in (re.sub(r"\s+", " ", str(x)).strip() for x in texts) if t]


def build_profile_text(profile: ProfileTextInput) -> ProfileText:
    """Assemble the versioned text. Raises ``ValueError`` when there is nothing to embed."""
    snapshot = profile.snapshot or {}
    labelled: list[tuple[str, str]] = []

    roles = _labels(list(profile.target_roles) if profile.target_roles else None)
    if roles:
        labelled.append(("Target role", "; ".join(roles)))

    headline = snapshot.get("headline") if isinstance(snapshot.get("headline"), str) else ""
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), str) else ""
    parts = [p.strip() for p in (headline, summary) if p and p.strip()]
    if len(parts) == 2 and parts[0].casefold() == parts[1].casefold():
        parts = parts[:1]
    summary_text = _scrub(" ".join(_sentence(p) for p in parts), snapshot) if parts else ""
    if summary_text:
        labelled.append(("Summary", summary_text))

    skills = _labels([
        *[s for s in (snapshot.get("skills") or []) if isinstance(s, str)],
        *[s for entry in _entries(snapshot, "experience") for s in (entry.get("skills") or []) if isinstance(s, str)],
        *[s for entry in _entries(snapshot, "projects") for s in (entry.get("skills") or []) if isinstance(s, str)],
    ])
    if skills:
        labelled.append(("Demonstrated skills", ", ".join(skills)))

    held = _labels([e.get("role") or e.get("title") or "" for e in _entries(snapshot, "experience")])
    if held:
        labelled.append(("Roles", _scrub("; ".join(held), snapshot)))
    projects = _labels([e.get("name") or "" for e in _entries(snapshot, "projects")])
    if projects:
        labelled.append(("Projects", _scrub("; ".join(projects), snapshot)))
    bullets = _bullet_texts(snapshot)
    if bullets:
        highlights = _scrub(" ".join(_sentence(b) for b in bullets), snapshot)
        if highlights:
            labelled.append(("Highlights", highlights))

    labelled = [(label, value) for label, value in labelled if value]
    if not labelled:
        raise ValueError("the profile has no confirmed content to build embedding text from")

    text = "\n".join(f"{label}: {value}" for label, value in labelled)
    truncated = len(text) > MAX_TEXT_CHARS
    if truncated:
        text = text[:MAX_TEXT_CHARS].rsplit(" ", 1)[0]
    return ProfileText(
        text=text,
        version=PROFILE_TEXT_VERSION,
        included=tuple(label for label, _ in labelled),
        truncated=truncated,
    )
