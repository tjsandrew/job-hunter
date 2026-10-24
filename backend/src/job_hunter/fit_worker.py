"""Lambda entry point of the fit-analysis worker (``job_hunter.fit_worker.handler``).

It runs OUTSIDE the VPC (the model is on the internet) and never touches the database. S3 invokes it when the API writes
``fit-requests/<id>.json``; it runs the analysis and writes ``fit-results/<id>.json`` next to it. A failure is written as
``{"error": "<code>"}`` so the web app learns about it at once instead of waiting for a timeout.

Environment: DOCUMENT_BUCKET, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, optional LLM_REASONING_EFFORT and LLM_TIMEOUT_SECONDS.
Settings are read straight from the environment: ``job_hunter.config`` would reject a Lambda that has no Cognito settings.
"""
from __future__ import annotations

import json
import logging
import os
from urllib.parse import unquote_plus

from job_hunter.fit_transport import MAX_FILE, REQUEST_PREFIX, result_key, run_request
from job_hunter.llm import HostedClient, LlmError
from job_hunter.preparation.fit.requirements import NoRequirements

log = logging.getLogger(__name__)


def _client() -> HostedClient:
    return HostedClient(os.getenv("LLM_BASE_URL", ""), os.getenv("LLM_API_KEY", ""), os.getenv("LLM_MODEL", ""),
                        int(os.getenv("LLM_TIMEOUT_SECONDS") or 120), os.getenv("LLM_REASONING_EFFORT", ""))


def process(s3, bucket: str, key: str, client=None) -> str:
    """Handle one request object; returns ``"ok"`` or the error code that was written."""
    try:
        request = json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read(MAX_FILE))
        analysis_id = request["analysis_id"]
        if key != f"{REQUEST_PREFIX}{analysis_id}.json":
            raise ValueError("request key does not match its analysis id")
    except Exception:
        log.exception("unreadable fit request %s", key)
        return "BAD_REQUEST"
    try:
        body, outcome = run_request(client or _client(), request), "ok"
    except NoRequirements:
        body, outcome = {"error": "NO_REQUIREMENTS"}, "NO_REQUIREMENTS"
    except LlmError as exc:
        log.warning("model failed for %s: %s", analysis_id, exc)     # LlmError text never contains the key
        body, outcome = {"error": "MODEL_UNAVAILABLE"}, "MODEL_UNAVAILABLE"
    except Exception:
        log.exception("fit analysis %s failed", analysis_id)
        body, outcome = {"error": "ANALYSIS_FAILED"}, "ANALYSIS_FAILED"
    s3.put_object(Bucket=bucket, Key=result_key(analysis_id), Body=json.dumps(body).encode(), ContentType="application/json")
    return outcome


def handler(event, context=None):
    import boto3
    s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION") or "ap-southeast-1")
    outcomes = []
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])
        if bucket == os.getenv("DOCUMENT_BUCKET") and key.startswith(REQUEST_PREFIX):
            outcomes.append(process(s3, bucket, key))
    return {"processed": len(outcomes), "outcomes": outcomes}
