"""The jobs the shared LLM worker can do. Adding an AI feature means adding one function here (docs/design/12-FIT-ANALYSIS.md).

A task takes a model client and the request's ``input`` and returns a JSON-able answer. It raises ``TaskError(code)`` for a
failure the user should see by name; anything else becomes a generic failure code. Both the Lambda worker and the local
(inline) path run tasks through ``run_task``, so they behave the same.

The answer comes from an untrusted place (a model, then a file in S3): the API re-checks it before it stores or uses it.
Task imports are inside the functions so importing this module stays cheap and free of circular imports.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Mapping

from job_hunter.llm.client import LlmClient, LlmError

log = logging.getLogger(__name__)


class TaskError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def run_fit(client: LlmClient, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Job fit analysis (design brief 12): requirements, verdicts, suggestions."""
    from job_hunter.preparation.fit.requirements import NoRequirements
    from job_hunter.preparation.fit.service import analyse_evidence
    try:
        return analyse_evidence(client, payload["job"], payload["evidence"], requirements=payload.get("requirements") or None)
    except NoRequirements as exc:
        raise TaskError("NO_REQUIREMENTS") from exc


def run_tailor(client: LlmClient, payload: Mapping[str, Any]) -> dict[str, Any]:
    """AI resume rewrite: the bullets reworded for a job. The API keeps only the rewrites that pass its fact check."""
    from job_hunter.preparation.tailor_llm import AiUnavailable, LlmRewriter
    try:
        return {"entries": LlmRewriter(client).rewrite(payload["entries"], payload["job"])}
    except AiUnavailable as exc:
        raise TaskError("MODEL_UNAVAILABLE") from exc


TASKS: dict[str, Callable[[LlmClient, Mapping[str, Any]], dict[str, Any]]] = {"fit": run_fit, "tailor": run_tailor}


def run_task(client: LlmClient, request: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    """Run one request. Returns the answer to store and an outcome label: ``"ok"`` or the error code (the answer is then
    ``{"error": code}``, so the web app learns about a failure at once instead of waiting for a timeout)."""
    task = TASKS.get(request.get("task"))
    if task is None:
        return {"error": "UNKNOWN_TASK"}, "UNKNOWN_TASK"
    try:
        return task(client, request["input"]), "ok"
    except TaskError as exc:
        return {"error": exc.code}, exc.code
    except LlmError as exc:
        log.warning("model failed for %s: %s", request.get("request_id"), exc)     # LlmError text never contains the key
        return {"error": "MODEL_UNAVAILABLE"}, "MODEL_UNAVAILABLE"
    except Exception:
        log.exception("task %s failed for %s", request.get("task"), request.get("request_id"))
        return {"error": "ANALYSIS_FAILED"}, "ANALYSIS_FAILED"
