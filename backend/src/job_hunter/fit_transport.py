"""How a fit analysis request reaches the model and how the answer comes back.

* ``"inline"`` (local development): the API process calls the model itself, after the response, in a background task.
* ``"s3"`` (AWS): the API Lambda sits in a VPC with no internet, so it cannot reach the model. It writes
  ``fit-requests/<id>.json`` to the private documents bucket; S3 invokes the fit-worker Lambda, which runs outside the VPC,
  calls the model and writes ``fit-results/<id>.json``. The API reads that file when the web app polls.

The request carries only what the model needs: the posting text, the already extracted requirements (when cached) and the
profile evidence text. The worker has no database access.

This module reads no settings, so the worker can import it without a full API environment.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

REQUEST_PREFIX = "fit-requests/"
RESULT_PREFIX = "fit-results/"
MAX_FILE = 2 * 1024 * 1024


def request_key(analysis_id) -> str:
    return f"{REQUEST_PREFIX}{analysis_id}.json"


def result_key(analysis_id) -> str:
    return f"{RESULT_PREFIX}{analysis_id}.json"


def build_request(analysis_id, job: Mapping[str, Any], evidence: Mapping[str, str], requirements: list | None) -> dict[str, Any]:
    return {"analysis_id": str(analysis_id),
            "job": {"title": job.get("title"), "description": job.get("description")},
            "evidence": dict(evidence), "requirements": requirements}


def run_request(client, request: Mapping[str, Any]) -> dict[str, Any]:
    """Run one request with a model client. Shared by the inline path and the worker so both do the same thing."""
    from job_hunter.preparation.fit.service import analyse_evidence
    return analyse_evidence(client, request["job"], request["evidence"], requirements=request.get("requirements") or None)


def put_request(s3, bucket: str, request: Mapping[str, Any]) -> None:
    s3.put_object(Bucket=bucket, Key=request_key(request["analysis_id"]), Body=json.dumps(request).encode(),
                  ContentType="application/json")


def get_result(s3, bucket: str, analysis_id) -> dict[str, Any] | None:
    """The worker's result file, or ``None`` while it does not exist yet."""
    try:
        body = s3.get_object(Bucket=bucket, Key=result_key(analysis_id))["Body"].read(MAX_FILE + 1)
    except s3.exceptions.NoSuchKey:
        return None
    if len(body) > MAX_FILE:
        raise ValueError("result file too large")
    return json.loads(body)
