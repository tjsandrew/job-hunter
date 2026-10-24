"""Read a job posting's real requirements with the language model (once per job; the caller caches the result)."""
from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping

from job_hunter.llm import LlmClient, LlmError, complete_validated
from job_hunter.preparation.fit import prompts

MAX_REQUIREMENTS = 15
MIN_DESCRIPTION = 120   # a posting shorter than this has no requirements to read; the API refuses it before using the model


class NoRequirements(LlmError):
    """The model read the posting and found no requirements in it."""


def input_hash(job: Mapping[str, Any]) -> str:
    """Changes when the posting or the prompt changes, so a cached extraction can be reused safely."""
    raw = "\n".join([prompts.PROMPT_VERSION, job.get("title") or "", job.get("description") or ""])
    return hashlib.sha256(raw.encode()).hexdigest()


# Lines a small model sometimes lists as requirements although they describe the offer or the process, not the candidate.
_NOT_A_REQUIREMENT = re.compile(
    r"(\$\s?\d|\bS\$|\bsalary\b|\bcompensation\b|per (?:month|annum|year|hour)\b|e-?verify|equal opportunity|"
    r"reasonable accommodations?|privacy (?:notice|policy)|applications? (?:are |is )?(?:limited|capped)|"
    r"limit(?:ed)? (?:of|to) \d+ applications?|\bapply (?:by|before)\b|closing date)", re.IGNORECASE)


def _validate(data: dict) -> list[dict[str, str]]:
    rows = data["requirements"]
    if not isinstance(rows, list):
        raise ValueError("requirements must be a list")
    seen, result = set(), []
    for row in rows:
        text = row.get("text") if isinstance(row, dict) else row
        if not isinstance(text, str):
            continue
        text = re.sub(r"\s+", " ", text).strip()
        key = text.casefold()
        if len(text) < 6 or not re.search(r"[A-Za-z]", text) or key in seen or _NOT_A_REQUIREMENT.search(text):
            continue
        seen.add(key)
        importance = row.get("importance") if isinstance(row, dict) else None
        result.append({"text": text[:240], "importance": "nice" if importance == "nice" else "must"})
    if not result:
        raise ValueError("no usable requirements")
    return result[:MAX_REQUIREMENTS]


def normalise(rows: Any) -> list[dict[str, str]]:
    """Clean requirement rows from any source (model, cache or a worker's result file); raises ``ValueError`` if none are usable."""
    return _validate({"requirements": rows})


def extract_requirements(client: LlmClient, job: Mapping[str, Any]) -> list[dict[str, str]]:
    try:
        return complete_validated(client, prompts.EXTRACT_SYSTEM, prompts.extract_user(job), _validate, max_tokens=900)
    except LlmError as exc:
        if "no usable requirements" in str(exc):
            raise NoRequirements(str(exc)) from exc
        raise
