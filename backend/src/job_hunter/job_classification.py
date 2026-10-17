"""Classification values to persist with an ingested job."""

from __future__ import annotations

from typing import Any, Sequence

from job_hunter.role_family import CLASSIFIER_VERSION, classify_role_family
from job_hunter.seniority import classify_seniority


def classify_job(title: str, stated_seniority: str | Sequence[str] | None = None) -> dict[str, Any]:
    """Classify a normalized title before saving the job; stated levels come from the source."""
    category, category_evidence = classify_role_family(title)
    seniority, seniority_source, seniority_evidence = classify_seniority(title, stated=stated_seniority)
    return {
        "category": category,
        "category_source": CLASSIFIER_VERSION,
        "category_evidence": category_evidence,
        "seniority": seniority,
        "seniority_source": seniority_source,
        "seniority_evidence": seniority_evidence,
    }
