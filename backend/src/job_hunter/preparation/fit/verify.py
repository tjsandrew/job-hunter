"""Check a result that came back from outside the API (the cloud worker's file) before it is stored or shown.

The worker already ran the same checks, but a result file is input like any other: nothing in it is trusted. Evidence ids
are matched against the user's own profile again, suggestions are re-checked, and the coverage number is recomputed here.
"""
from __future__ import annotations

from typing import Any, Mapping

from job_hunter.preparation.fit import grounding, prompts
from job_hunter.preparation.fit.coverage import coverage
from job_hunter.preparation.fit.requirements import normalise

MAX_MODEL_NAME = 120
MAX_SUGGESTIONS = 5


def verify_result(raw: Any, evidence: Mapping[str, str]) -> dict[str, Any]:
    """The result as the app will store it. Raises ``ValueError`` when the file is not a usable analysis."""
    if not isinstance(raw, Mapping):
        raise ValueError("result is not an object")
    requirements = normalise(raw.get("requirements"))
    rows = raw.get("verdicts")
    if not isinstance(rows, list) or len(rows) != len(requirements):
        raise ValueError("there must be one verdict per requirement")
    verdicts = [grounding.check_verdict(None if isinstance(row, Mapping) and row.get("answered") is False else row, requirement, evidence)
                for row, requirement in zip(rows, requirements)]
    texts = [r["text"] for r in requirements]
    raw_suggestions = raw.get("suggestions") if isinstance(raw.get("suggestions"), list) else []
    suggestions = [s for s in (grounding.check_suggestion(row, len(requirements), evidence, texts) for row in raw_suggestions) if s]
    return {
        "prompt_version": prompts.PROMPT_VERSION,
        "model": str(raw.get("model") or "unknown")[:MAX_MODEL_NAME],
        "requirements": requirements,
        "verdicts": verdicts,
        "suggestions": suggestions[:MAX_SUGGESTIONS],
        "coverage": coverage(requirements, verdicts),
        "evidence": {key: evidence[key] for v in verdicts for key in v["evidence"]},
    }
