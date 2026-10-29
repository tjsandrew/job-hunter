"""B4: run one job pull on staging and record what it did and how long each stage took.

Usage (from the repository root, evaluation virtualenv, operator SSO session):
    AWS_PROFILE=<operator profile> python eval/b4_pull.py [max_new]      # default 10, as the Pull jobs workflow

It calls the same functions as scripts/pull_jobs.py (so it refuses to run while staging is paused), keeps the full
answer (fetched, new / updated / unchanged / deferred, failures, truncated boards), then waits for the embedding
worker to finish the new jobs and takes the stage times from the Lambda logs:
  discovery start -> import finished -> embedding finished (the new jobs can rank in For you from then on).
Writes eval/results/b4-pulls/<UTC time>.json. Run it once or twice a day; analyse_b4.py tallies all of them.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pull_jobs  # noqa: E402

REGION, PREFIX = "ap-southeast-1", "jobhunter-staging"
OUT = ROOT / "eval" / "results" / "b4-pulls"
EMBED_WAIT_SECONDS = 900


def iso(ms: int | None) -> str | None:
    return None if ms is None else datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"


def events(logs, function: str, start_ms: int, pattern: str = "") -> list[dict]:
    pages = logs.get_paginator("filter_log_events").paginate(
        logGroupName=f"/aws/lambda/{PREFIX}-{function}", startTime=start_ms, filterPattern=pattern)
    return sorted((event for page in pages for event in page["events"]), key=lambda event: event["timestamp"])


def last_report(logs, function: str, start_ms: int) -> int | None:
    reports = events(logs, function, start_ms, '"REPORT RequestId"')
    return reports[-1]["timestamp"] if reports else None


def main() -> int:
    max_new = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    client = boto3.client("lambda", region_name=REGION, config=Config(read_timeout=900, retries={"max_attempts": 0}))
    logs = boto3.client("logs", region_name=REGION)
    if pull_jobs.paused(client, f"{PREFIX}-api"):
        print("Staging is paused; not pulling.", file=sys.stderr)
        return 1
    started = int(time.time() * 1000)
    result = pull_jobs.pull(client, f"{PREFIX}-discovery", max_new)
    returned = int(time.time() * 1000)
    imported = result.get("import") or {}
    print(pull_jobs.summary(result))

    time.sleep(20)                                     # let the import's REPORT line arrive
    import_end = last_report(logs, "import", started)
    embed_end = None
    if imported.get("new"):
        deadline = time.time() + EMBED_WAIT_SECONDS
        while time.time() < deadline:                  # the worker logs one "embedding pass" per run; done when nothing remains
            passes = [event for event in events(logs, "embed", returned - 5000, '"embedding pass"')
                      if "'remaining': False" in event["message"] and "'jobs': {'ready'" in event["message"]]
            if passes:
                embed_end = passes[-1]["timestamp"]
                break
            time.sleep(30)
    record = {"started_at": iso(started), "discovery_returned_at": iso(returned), "import_finished_at": iso(import_end),
              "embedding_finished_at": iso(embed_end), "max_new": max_new,
              "seconds": {"discovery_and_import": round((returned - started) / 1000, 1),
                          "to_import_finished": round((import_end - started) / 1000, 1) if import_end else None,
                          "to_embedding_finished": round((embed_end - started) / 1000, 1) if embed_end else None},
              "result": result}
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(record, indent=2))
    print(json.dumps(record["seconds"]), "->", path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
