"""Run one fit analysis: requirements -> verdicts -> suggestions -> coverage. Pure; callers handle storage and quota."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from job_hunter.llm import LlmClient
from job_hunter.preparation.fit import grounding, prompts
from job_hunter.preparation.fit.coverage import coverage
from job_hunter.preparation.fit.judge import judge, suggest
from job_hunter.preparation.fit.requirements import extract_requirements


def analyse(client: LlmClient, job: Mapping[str, Any], snapshot: Mapping[str, Any], *,
            requirements: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """``requirements`` may be passed from the per-job cache; otherwise they are extracted from the posting."""
    return analyse_evidence(client, job, grounding.evidence_from_snapshot(snapshot), requirements=requirements)


def analyse_evidence(client: LlmClient, job: Mapping[str, Any], evidence: Mapping[str, str], *,
                     requirements: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """The same analysis from the evidence text alone, which is all a worker without database access needs."""
    reqs =[dict(r) for r in requirements] if requirements else extract_requirements(client, job)
    verdicts = judge(client, reqs, evidence)
    return {
        "prompt_version": prompts.PROMPT_VERSION,
        "model": client.name,
        "requirements": reqs,
        "verdicts": verdicts,
        "suggestions": suggest(client, reqs, verdicts, evidence),
        "coverage": coverage(reqs, verdicts),
        "evidence": {key: evidence[key] for v in verdicts for key in v["evidence"]},
    }
