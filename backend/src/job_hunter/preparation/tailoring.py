from typing import Any, Mapping

from job_hunter.recommendations import (
    _SKILL_ALIASES, _canonical_skill, _job_document, _job_skills, _normalise_phrase, _tokenize,
)


def _resume_text(content: Mapping[str, Any]) -> str:
    parts = [content.get("summary") or ""]
    for section in content.get("sections", []):
        for entry in section.get("entries", []):
            parts += [entry.get("heading") or "", entry.get("subheading") or "", *entry.get("bullets", [])]
    return _normalise_phrase(" ".join(parts))


def _has_skill(text: str, skill: str) -> bool:
    canonical = _canonical_skill(skill)
    return any(f" {_normalise_phrase(alias)} " in f" {text} " for alias in _SKILL_ALIASES.get(canonical, (canonical,)))


def _terms(text: str) -> set[str]:
    return {_canonical_skill(token) for token in _tokenize(text)}


def _sort_bullets(entry: dict, keywords: set[str]) -> dict:
    bullets = entry.get("bullets", [])
    order = sorted(range(len(bullets)), key=lambda i: -len(keywords & _terms(bullets[i])))
    result = {**entry, "bullets": [bullets[i] for i in order]}
    if entry.get("bullet_sources") is not None:
        result["bullet_sources"] = [entry["bullet_sources"][i] for i in order]
    return result


def tailor(content: Mapping[str, Any], job: Mapping[str, Any]) -> tuple[dict, dict[str, list[str]]]:
    keywords = _terms(_job_document(job))
    sections = [{**section, "entries": [_sort_bullets(entry, keywords) for entry in section.get("entries", [])]}
                for section in content.get("sections", [])]
    text = _resume_text(content)
    skills = _job_skills(job)
    return ({**content, "sections": sections},
            {"matched": [s for s in skills if _has_skill(text, s)], "missing": [s for s in skills if not _has_skill(text, s)]})
