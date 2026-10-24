"""How a request for the shared LLM worker reaches the model and how the answer comes back.

* ``"inline"`` (local development, ``LLM_WORKER=inline``): the API process calls the model itself.
* ``"s3"`` (AWS, ``LLM_WORKER=s3``): the API Lambda sits in a VPC with no internet, so it cannot reach the model. It writes
  ``llm-requests/<id>.json`` to the private documents bucket; S3 invokes the LLM worker Lambda, which runs outside the VPC,
  calls the model and writes ``llm-results/<id>.json``. The API reads that file, either when the web app polls (fit analysis)
  or by waiting a few seconds inside the request (``ask``, used by the AI resume rewrite).

A request is ``{"request_id", "task", "input"}``. ``task`` names an entry of ``job_hunter.llm.tasks.TASKS``; ``input`` is what
that task needs and nothing more. The worker has no database access.

This module reads no settings, so the worker can import it without a full API environment.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Mapping
from uuid import uuid4

REQUEST_PREFIX = "llm-requests/"
RESULT_PREFIX = "llm-results/"
MAX_FILE = 2 * 1024 * 1024


def request_key(request_id) -> str:
    return f"{REQUEST_PREFIX}{request_id}.json"


def result_key(request_id) -> str:
    return f"{RESULT_PREFIX}{request_id}.json"


def build_request(task: str, request_id, payload: Mapping[str, Any]) -> dict[str, Any]:
    return {"request_id": str(request_id), "task": task, "input": dict(payload)}


def put_request(s3, bucket: str, request: Mapping[str, Any]) -> None:
    s3.put_object(Bucket=bucket, Key=request_key(request["request_id"]), Body=json.dumps(request).encode(),
                  ContentType="application/json")


def get_result(s3, bucket: str, request_id) -> dict[str, Any] | None:
    """The worker's result file, or ``None`` while it does not exist yet."""
    try:
        body = s3.get_object(Bucket=bucket, Key=result_key(request_id))["Body"].read(MAX_FILE + 1)
    except s3.exceptions.NoSuchKey:
        return None
    if len(body) > MAX_FILE:
        raise ValueError("result file too large")
    return json.loads(body)


def ask(s3, bucket: str, task: str, payload: Mapping[str, Any], *, wait_seconds: float, interval: float = 1.0,
        sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> dict[str, Any] | None:
    """Send one request and wait for its answer: the result (which may be ``{"error": code}``), or ``None`` if the worker
    has not answered after ``wait_seconds``. For short tasks only: the caller itself has a time limit."""
    request = build_request(task, uuid4(), payload)
    put_request(s3, bucket, request)
    deadline = clock() + wait_seconds
    while True:
        sleep(interval)             # S3 needs about a second to wake the worker, so the first look comes after a pause
        result = get_result(s3, bucket, request["request_id"])
        if result is not None or clock() >= deadline:
            return result
