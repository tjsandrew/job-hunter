"""Lambda entry point that pulls public job listings (``job_hunter.discovery_worker.handler``).

It runs OUTSIDE the VPC (the job feeds are on the internet) and never touches the database. One invocation:

1. reads the configured Greenhouse / Lever / SmartRecruiters boards and MyCareersFuture searches (Singapore only);
2. stores the normalised records as ``imports/<pull id>.json`` in the documents bucket;
3. invokes the import Lambda (inside the VPC, which can reach Aurora) with that object's name and the batch size, and
   returns its counts.

Start it from the "Pull jobs" GitHub workflow (``scripts/pull_jobs.py``) or, when enabled, from the EventBridge schedule.
Event: optional ``{"max_new": 10}``; any other content (an EventBridge scheduled event, for example) is ignored.

Environment: DOCUMENT_BUCKET, IMPORT_FUNCTION, GREENHOUSE_BOARDS, LEVER_BOARDS, SMARTRECRUITERS_BOARDS,
MYCAREERSFUTURE_SEARCHES, ADZUNA_SEARCHES (comma separated), ADZUNA_APP_ID and ADZUNA_APP_KEY (only with ADZUNA_SEARCHES), optional DISCOVERY_MAX_NEW, DISCOVERY_MAX_PAGES, DISCOVERY_TIMEOUT_SECONDS.
Settings are read straight from the environment: ``job_hunter.config`` would reject a Lambda that has no Cognito settings.
"""
from __future__ import annotations

import json
import logging
import os
from uuid import uuid4

from job_hunter.import_jobs import snapshot_payload
from job_hunter.ingestion.discovery import DiscoveryConfig, discover_report
from job_hunter.job_pull import DEFAULT_MAX_NEW, clamp_max_new, import_key

log = logging.getLogger(__name__)


def _names(variable: str) -> list[str]:
    return [value.strip() for value in os.getenv(variable, "").split(",") if value.strip()]


def build_config() -> DiscoveryConfig:
    return DiscoveryConfig(
        greenhouse_boards=_names("GREENHOUSE_BOARDS"),
        lever_boards=_names("LEVER_BOARDS"),
        smartrecruiters_boards=_names("SMARTRECRUITERS_BOARDS"),
        mycareersfuture_searches=_names("MYCAREERSFUTURE_SEARCHES"),
        adzuna_searches=_names("ADZUNA_SEARCHES"),      # also needs ADZUNA_APP_ID / ADZUNA_APP_KEY (GitHub secrets, set at release)
        timeout_seconds=float(os.getenv("DISCOVERY_TIMEOUT_SECONDS") or 15),
        max_pages_per_board=int(os.getenv("DISCOVERY_MAX_PAGES") or 5),
        singapore_only=True,        # the filter runs after the per-board cap, so keep that cap high
    )


def pull(s3, lambda_client, *, bucket: str, import_function: str, max_new: int, config: DiscoveryConfig | None = None) -> dict:
    report = discover_report(config or build_config())
    result: dict = {"fetched": len(report.jobs), "failures": report.failures, "truncated_boards": report.truncated_boards,
                    "max_new": max_new}
    if not report.jobs:
        result["import"] = None      # every source failed or returned nothing: nothing to load
        return result
    pull_id = str(uuid4())
    key = import_key(pull_id)
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(snapshot_payload(report), ensure_ascii=False).encode(),
                  ContentType="application/json")
    response = lambda_client.invoke(FunctionName=import_function, InvocationType="RequestResponse",
                                    Payload=json.dumps({"bucket": bucket, "key": key, "max_new": max_new}).encode())
    body = response["Payload"].read().decode("utf-8", "replace")
    if response.get("FunctionError"):
        raise RuntimeError(f"import step failed: {body[:500]}")
    result["snapshot"] = key
    result["import"] = json.loads(body)
    return result


def handler(event, context=None):
    import boto3
    region = os.getenv("AWS_REGION") or "ap-southeast-1"
    bucket = os.environ["DOCUMENT_BUCKET"]
    import_function = os.environ["IMPORT_FUNCTION"]
    requested = event.get("max_new") if isinstance(event, dict) else None
    max_new = clamp_max_new(requested if requested is not None else os.getenv("DISCOVERY_MAX_NEW"), DEFAULT_MAX_NEW)
    # The import step may wait for Aurora to resume, so wait longer than boto3's 60 s default, and never retry a
    # timed-out invoke (a retry would run the import twice).
    from botocore.config import Config
    lambda_client = boto3.client("lambda", region_name=region, config=Config(read_timeout=280, connect_timeout=10,
                                                                             retries={"total_max_attempts": 1}))
    result = pull(boto3.client("s3", region_name=region), lambda_client,
                  bucket=bucket, import_function=import_function, max_new=max_new)
    log.info("pull finished: %s", {key: value for key, value in result.items() if key != "failures"})
    return result
