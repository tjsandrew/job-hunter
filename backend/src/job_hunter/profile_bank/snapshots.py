"""Stable profile read contract and contact-free embedding input."""
from copy import deepcopy
from collections.abc import Mapping
import re

EMBEDDING_TEXT_VERSION = "profile-v1"


def _get(item, key, default=None):
    return item.get(key, default) if isinstance(item, Mapping) else getattr(item, key, default)


def _dates(data):
    if data.get("dates_text"):
        return data["dates_text"]
    start = data.get("start") or ""
    end = "Present" if data.get("current") else data.get("end") or ""
    return f"{start}–{end}" if start and end else start or end


def assemble_profile_snapshot(basics: dict, items, bank_revision: int) -> dict:
    snapshot = deepcopy(basics)
    for key in ("skills", "experience", "education", "projects"):
        snapshot[key] = []
    snapshot["bank_revision"] = bank_revision
    snapshot["bullets"] = []
    ordered = sorted(items, key=lambda item: (_get(item, "kind"), _get(item, "position", 0), str(_get(item, "id"))))
    for item in ordered:
        if _get(item, "archived_at") is not None:
            continue
        kind, data = _get(item, "kind"), _get(item, "data", {})
        legacy = deepcopy(data.get("legacy_fields", {}))
        if kind == "skill":
            snapshot["skills"].append(data["name"])
        elif kind in ("experience", "education", "project"):
            if kind == "experience":
                canonical = {"role": data.get("title", ""), "company": data.get("organisation", ""), "dates": _dates(data), "skills": deepcopy(data.get("skills", []))}
                key = "experience"
            elif kind == "education":
                canonical = {"degree": data.get("qualification", ""), "school": data.get("institution", ""), "dates": _dates(data)}
                key = "education"
            else:
                canonical = {"name": data.get("name", ""), "role": data.get("role", ""), "url": data.get("url", ""), "dates": _dates(data), "skills": deepcopy(data.get("skills", []))}
                key = "projects"
            # Keep legacy optional keys and date spelling for exact compatibility,
            # but reflect edits to the corresponding bank facts.
            for field, value in canonical.items():
                if field == "dates" and field in legacy and not data.get("dates_text"):
                    from .dates import normalize_dates
                    old = normalize_dates(legacy[field])
                    if all(old.get(k) == data.get(k) for k in ("start", "end", "current")):
                        value = legacy[field]
                if field in legacy or not data.get("legacy_fields"):
                    legacy[field] = value
            if "bullets" in legacy:
                legacy["bullets"] = [bullet["text"] for bullet in data.get("bullets", [])]
            snapshot[key].append(legacy)
        for point in data.get("bullets", []):
            snapshot["bullets"].append({"id": point["id"], "item_id": str(_get(item, "id")), "text": point["text"], "tags": deepcopy(point.get("tags", [])), "skills": deepcopy(point.get("skills", []))})
    return snapshot


def profile_embedding_text(snapshot: dict) -> str:
    """Profile-v1: only headline, summary, roles, skills and main points.

    Contact fields are excluded by an allowlist and their known values are
    removed even when repeated inside a summary or achievement.
    """
    pieces = []
    for key in ("headline", "summary"):
        if isinstance(snapshot.get(key), str):
            pieces.append(snapshot[key])
    pieces.extend(value for value in snapshot.get("skills", []) if isinstance(value, str))
    for entry in snapshot.get("experience", []):
        pieces.append(entry.get("role", entry.get("title", "")))
        pieces.extend(value for value in entry.get("skills", []) if isinstance(value, str))
    for entry in snapshot.get("projects", []):
        pieces.append(entry.get("name", ""))
        pieces.extend(value for value in entry.get("skills", []) if isinstance(value, str))
    points = snapshot.get("bullets")
    if points is not None:
        pieces.extend(point.get("text", "") for point in points)
    else:  # Confirmed snapshots predating the bank.
        for key in ("experience", "projects"):
            for entry in snapshot.get(key, []):
                pieces.extend(point if isinstance(point, str) else point.get("text", "") for point in entry.get("bullets", []))
    text = "\n".join(str(piece).strip() for piece in pieces if piece)
    contacts = []
    def collect(value):
        if isinstance(value, str) and value.strip():
            contacts.append(value.strip())
        elif isinstance(value, Mapping):
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
    for key in ("name", "display_name", "email", "phone", "links", "location"):
        collect(snapshot.get(key))
    for value in sorted(contacts, key=len, reverse=True):
        text = re.sub(r"(?<!\w)" + re.escape(value) + r"(?!\w)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b|https?://\S+", "", text)
    text = re.sub(r"(?<!\w)\+?\d[\d .()/-]{7,}\d(?!\w)", "", text)
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())
