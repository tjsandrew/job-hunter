"""Lambda entry point of the shared LLM worker (``job_hunter.llm_worker.handler``).

It runs OUTSIDE the VPC (the model is on the internet) and never touches the database. S3 invokes it when the API writes
``llm-requests/<id>.json``; it runs the request's task (``job_hunter.llm.tasks``) and writes ``llm-results/<id>.json`` next to
it. A failure is written as ``{"error": "<code>"}`` so the web app learns about it at once instead of waiting for a timeout.

Environment: DOCUMENT_BUCKET, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, optional LLM_REASONING_EFFORT and LLM_TIMEOUT_SECONDS.
Settings are read straight from the environment: ``job_hunter.config`` would reject a Lambda that has no Cognito settings.

Each request logs one JSON line (``"event": "llm_task"``): the task, its outcome, how long the request file waited for
the worker, the model calls, their time and token counts. The system evaluation reads these for timing and cost.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from urllib.parse import unquote_plus

from job_hunter.llm import HostedClient, LlmError
from job_hunter.llm.tasks import run_task
from job_hunter.llm_transport import MAX_FILE, REQUEST_PREFIX, request_key, result_key

log = logging.getLogger(__name__)


def _client() -> HostedClient:
    return HostedClient(os.getenv("LLM_BASE_URL", ""), os.getenv("LLM_API_KEY", ""), os.getenv("LLM_MODEL", ""),
                        int(os.getenv("LLM_TIMEOUT_SECONDS") or 120), os.getenv("LLM_REASONING_EFFORT", ""))


class _Metered:
    """Wraps the model client to add up the task's model calls, time and tokens (a task may call the model more than once)."""

    def __init__(self, client):
        self._client = client
        self.calls, self.model_ms, self.prompt_tokens, self.output_tokens = 0, 0.0, 0, 0

    def __getattr__(self, name):
        return getattr(self._client, name)

    def complete_json(self, system: str, user: str, *, max_tokens: int = 1024):
        before, started = getattr(self._client, "last_usage", None), time.perf_counter()
        try:
            return self._client.complete_json(system, user, max_tokens=max_tokens)
        finally:
            self.calls += 1
            self.model_ms += (time.perf_counter() - started) * 1000
            usage = getattr(self._client, "last_usage", None)
            if usage is not None and usage is not before:      # a failed call leaves the previous call's counts in place
                self.prompt_tokens += usage.get("prompt_tokens") or 0
                self.output_tokens += usage.get("output_tokens") or 0


def _waited_ms(event_time: str | None) -> int | None:
    """Milliseconds from S3 storing the request file (the event's ``eventTime``) to now."""
    try:
        stored = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return round((time.time() - stored.timestamp()) * 1000)


def process(s3, bucket: str, key: str, client=None, waited_ms: int | None = None) -> str:
    """Handle one request object; returns ``"ok"`` or the error code that was written."""
    started = time.perf_counter()
    try:
        request = json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read(MAX_FILE))
        request_id = request["request_id"]
        if key != request_key(request_id):
            raise ValueError("request key does not match its request id")
    except Exception:
        log.exception("unreadable LLM request %s", key)
        return "BAD_REQUEST"
    metered = None
    try:
        metered = _Metered(client or _client())
        body, outcome = run_task(metered, request)
    except LlmError:          # no key or URL configured: say so instead of leaving the user waiting
        body, outcome = {"error": "MODEL_UNAVAILABLE"}, "MODEL_UNAVAILABLE"
    s3.put_object(Bucket=bucket, Key=result_key(request_id), Body=json.dumps(body).encode(), ContentType="application/json")
    log.info(json.dumps({"event": "llm_task", "request_id": str(request_id), "task": request.get("task"), "outcome": outcome,
                         "waited_ms": waited_ms, "task_ms": round((time.perf_counter() - started) * 1000),
                         "model": getattr(metered, "name", None), "model_calls": metered.calls if metered else 0,
                         "model_ms": round(metered.model_ms) if metered else 0,
                         "prompt_tokens": metered.prompt_tokens if metered else 0,
                         "output_tokens": metered.output_tokens if metered else 0}))
    return outcome


def handler(event, context=None):
    import boto3
    logging.getLogger().setLevel(logging.INFO)
    s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION") or "ap-southeast-1")
    outcomes = []
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])
        if bucket == os.getenv("DOCUMENT_BUCKET") and key.startswith(REQUEST_PREFIX):
            outcomes.append(process(s3, bucket, key, waited_ms=_waited_ms(record.get("eventTime"))))
    return {"processed": len(outcomes), "outcomes": outcomes}
