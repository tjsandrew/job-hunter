"""Start one job pull on staging and print what it did (used by the "Pull jobs" workflow).

The discovery function reads the public job feeds, stores a snapshot in S3 and invokes the import function, which adds the next
few NEW jobs to the database. This script only invokes discovery and formats the answer as Markdown.
Environment: DISCOVERY_FUNCTION (required), API_FUNCTION (optional: used to refuse a pull while staging is paused), MAX_NEW.
"""
import json
import os
import sys

import boto3
from botocore.config import Config


def paused(client, api_function: str) -> bool:
    if not api_function:
        return False
    return client.get_function(FunctionName=api_function).get("Concurrency", {}).get("ReservedConcurrentExecutions") == 0


def pull(client, function: str, max_new: int) -> dict:
    # Synchronous: the import step may wait for Aurora to resume. Never retry, a retry would run the pull twice.
    response = client.invoke(FunctionName=function, InvocationType="RequestResponse",
                             Payload=json.dumps({"max_new": max_new}).encode())
    body = response["Payload"].read().decode("utf-8", "replace")
    if response.get("FunctionError"):
        raise RuntimeError(f"The job pull failed: {body[:1000]}")
    return json.loads(body)


def summary(result: dict) -> str:
    imported = result.get("import")
    lines = ["## Pull jobs", "", f"- Fetched from the job feeds (Singapore only): **{result.get('fetched', 0)}**"]
    if imported is None:
        lines.append("- Nothing was loaded: every source failed or returned no Singapore jobs.")
    else:
        lines += [
            f"- New jobs added: **{imported.get('new', 0)}** (batch size {result.get('max_new')})",
            f"- Already stored and refreshed or unchanged: {imported.get('updated', 0)} updated, {imported.get('unchanged', 0)} unchanged",
            f"- Left for the next pull: {imported.get('deferred', 0)}",
            f"- Closed: {imported.get('closed_expired', 0)} past their closing date, {imported.get('closed_unseen', 0)} not "
            f"listed by their source for 21 days; reopened (listed again): {imported.get('reopened', 0)}",
            f"- Records that could not be imported: {imported.get('errors', 0)}",
            f"- Embedding requested for the new jobs: {'yes' if imported.get('embed_flag_written') else 'no'}",
        ]
    for problem in (imported or {}).get("record_errors") or []:
        lines.append(f"- Record not imported: `{problem.get('source')}` id `{problem.get('external_id')}`: {problem.get('error')}")
    for failure in result.get("failures") or []:
        lines.append(f"- Source problem: `{json.dumps(failure)}`")
    for board in result.get("truncated_boards") or []:
        lines.append(f"- Stopped early on `{board}` (it has more postings than one pull reads)")
    if imported and imported.get("new"):
        lines += ["", "New jobs appear in Discover (All jobs) within a minute; the For you ranking includes them once the "
                      "embedding worker has run, usually a few minutes later."]
    return "\n".join(lines) + "\n"


def main() -> int:
    function = os.environ.get("DISCOVERY_FUNCTION", "")
    if not function:
        print("DISCOVERY_FUNCTION is not set; the job pull is not deployed.", file=sys.stderr)
        return 1
    try:
        max_new = int(os.environ.get("MAX_NEW") or 10)
    except ValueError:
        print("MAX_NEW must be a whole number.", file=sys.stderr)
        return 1
    client = boto3.client("lambda", config=Config(read_timeout=610, connect_timeout=10, retries={"total_max_attempts": 1}))
    if paused(client, os.environ.get("API_FUNCTION", "")):
        print("Staging is manually paused. Use Pause or resume staging backend first.", file=sys.stderr)
        return 1
    print(summary(pull(client, function, max_new)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
