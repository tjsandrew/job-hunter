"""Checks that keep a model's answer tied to what the profile and the posting actually say.

A model may cite evidence that does not exist or add facts of its own. Everything it returns passes through here:
unknown evidence ids are dropped, a "met" or "partly" verdict without real evidence is downgraded, and notes or
suggestions that introduce numbers found nowhere in the profile or the requirement are dropped.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

VERDICTS = ("met", "partly", "not_evidenced", "needs_judgement")
SUGGESTION_KINDS = ("emphasise", "reword", "add")
MAX_NOTE = 240
MAX_SUGGESTION = 320
_NUMBER = re.compile(r"\d[\d,.]*")


def evidence_from_snapshot(snapshot: Mapping[str, Any]) -> dict[str, str]:
    """Everything the model may cite, keyed by a stable id: profile bullet ids, ``skill:<name>``, roles, education, projects."""
    items: dict[str, str] = {}
    if isinstance(snapshot.get("summary"), str) and snapshot["summary"].strip():
        items["summary"] = snapshot["summary"].strip()
    for skill in snapshot.get("skills") or []:
        if isinstance(skill, str) and skill.strip():
            items[f"skill:{skill.strip()}"] = skill.strip()
    for index, entry in enumerate(snapshot.get("experience") or []):
        role = entry.get("role") or entry.get("title")
        company = entry.get("company") or entry.get("organisation")
        if role:
            items[f"role:{index}"] = f"{role} at {company}" if company else str(role)
    for index, entry in enumerate(snapshot.get("education") or []):
        degree = entry.get("degree") or entry.get("qualification")
        school = entry.get("school") or entry.get("institution")
        if degree:
            items[f"education:{index}"] = " ".join(str(part) for part in (degree, f"at {school}" if school else "", f"({entry['dates']})" if entry.get("dates") else "") if part)
    for index, entry in enumerate(snapshot.get("projects") or []):
        if entry.get("name"):
            items[f"project:{index}"] = str(entry["name"])
    for bullet in snapshot.get("bullets") or []:
        if isinstance(bullet.get("id"), str) and isinstance(bullet.get("text"), str) and bullet["text"].strip():
            items[bullet["id"]] = bullet["text"].strip()
    return items


_NAME = re.compile(r"\b[A-Z][A-Za-z0-9+#./-]{2,}")


def unknown_names(note: str, known_text: str) -> set[str]:
    """Capitalised names in a note (tools, employers, skills) that appear nowhere in ``known_text``.

    The first word of a sentence is ignored. A small model sometimes adds a tool it was never shown ("Spark")."""
    known = known_text.casefold()
    found = set()
    for match in _NAME.finditer(note or ""):
        before = (note or "")[:match.start()].rstrip()
        if before and before[-1] not in ".!?" and match.group().casefold().rstrip(".,") not in known:
            found.add(match.group())
    return found


def numbers(text: str) -> set[str]:
    return {match.rstrip(".,") for match in _NUMBER.findall(text or "")}


def _clean(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", value).strip()[:limit] if isinstance(value, str) else ""


def check_verdict(raw: Mapping[str, Any] | None, requirement: Mapping[str, Any], evidence: Mapping[str, str]) -> dict[str, Any]:
    """One requirement's verdict, with only real evidence ids and no invented numbers."""
    if not isinstance(raw, Mapping):
        return {"verdict": "needs_judgement", "evidence": [], "note": "The model gave no answer for this requirement.", "answered": False}
    verdict = raw.get("verdict") if raw.get("verdict") in VERDICTS else "needs_judgement"
    cited = [e for e in (raw.get("evidence") or []) if isinstance(e, str) and e in evidence]
    cited = list(dict.fromkeys(cited))[:4]
    if verdict in ("met", "partly") and not cited:
        verdict = "not_evidenced"
    note = _clean(raw.get("note"), MAX_NOTE)
    allowed = numbers(requirement.get("text", "")).union(*(numbers(evidence[e]) for e in cited)) if cited else numbers(requirement.get("text", ""))
    if note and not numbers(note) <= allowed:
        note = ""
    if note and unknown_names(note, " ".join(list(evidence.values()) + [requirement.get("text", "")])):
        note = ""         # names a tool or employer that neither the profile nor the requirement mentions
    return {"verdict": verdict, "evidence": cited, "note": note, "answered": True}


def check_suggestion(raw: Any, requirement_count: int, evidence: Mapping[str, str], requirement_texts: list[str]) -> dict[str, Any] | None:
    """A suggestion the user can act on, or ``None`` when it cannot be trusted."""
    if not isinstance(raw, Mapping) or raw.get("kind") not in SUGGESTION_KINDS:
        return None
    text = _clean(raw.get("text"), MAX_SUGGESTION)
    if len(text) < 10:
        return None
    known = numbers(" ".join(evidence.values())) | numbers(" ".join(requirement_texts))
    if not numbers(text) <= known:
        return None
    index = raw.get("requirement")
    index = index if isinstance(index, int) and 0 <= index < requirement_count else None
    bullet = raw.get("bullet_id")
    bullet = bullet if isinstance(bullet, str) and bullet in evidence else None
    if raw["kind"] in ("emphasise", "reword") and bullet is None:
        return None          # advice about existing experience must point at something the profile really says
    if raw["kind"] == "add" and not re.search(r"\bif\b", text, re.IGNORECASE):
        text = "If this is true for you: " + text[0].lower() + text[1:]
    return {"kind": raw["kind"], "requirement": index, "bullet_id": bullet, "text": text}
