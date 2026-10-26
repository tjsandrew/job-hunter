"""B4: tally the job pulls on staging: volume by source, failures, cross-source duplicates found, stage durations.

Usage (from the repository root, evaluation virtualenv, operator SSO session):
    AWS_PROFILE=<operator profile> python eval/analyse_b4.py

Reads every pull snapshot in the documents bucket (imports/*.json: what discovery fetched, its failures and truncated
searches), the measured pulls in eval/results/b4-pulls/*.json (new / already stored / deferred, stage times), and the
discovery and import functions' REPORT lines for the duration of every pull. Cross-source duplicates per pull are found
with the production rules (dedup.clusters within each match key, as the import's relink does).
Writes eval/results/b4-pipeline-<date>/summary.md and summary.json.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import boto3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
from job_hunter.ingestion import dedup  # noqa: E402

REGION, PREFIX = "ap-southeast-1", "jobhunter-staging"
PULLS = ROOT / "eval" / "results" / "b4-pulls"
SOURCES = ["greenhouse", "lever", "mycareersfuture", "adzuna"]


def bucket() -> str:
    config = boto3.client("lambda", region_name=REGION).get_function_configuration(FunctionName=f"{PREFIX}-llm")
    return config["Environment"]["Variables"]["DOCUMENT_BUCKET"]


def snapshots() -> list[dict]:
    s3 = boto3.client("s3", region_name=REGION)
    name = bucket()
    keys = [item["Key"] for page in s3.get_paginator("list_objects_v2").paginate(Bucket=name, Prefix="imports/")
            for item in page.get("Contents", []) if item["Key"].endswith(".json")]
    found = [json.loads(s3.get_object(Bucket=name, Key=key)["Body"].read()) for key in keys]
    return sorted(found, key=lambda snapshot: snapshot["saved_at"])


def duplicates(jobs: list[dict]) -> Counter:
    """Rows the production rules would mark as duplicates of another source's row, by source."""
    by_key = defaultdict(list)
    for index, job in enumerate(jobs):
        key = dedup.match_key(job.get("employer"), job.get("title"), job.get("location"))
        if key:
            by_key[key].append(SimpleNamespace(id=str(index), source=job["source"], source_url=job.get("source_url"),
                                               description=job.get("description"), match_key=key, posted_at=None))
    found = Counter()
    for rows in by_key.values():
        if len({row.source for row in rows}) < 2:
            continue
        for group in dedup.clusters(rows):
            if len({row.source for row in group}) > 1:
                ordered = sorted(group, key=dedup._preference)
                found.update(row.source for row in ordered[1:])
    return found


def reports(function: str, start_ms: int) -> list[dict]:
    logs = boto3.client("logs", region_name=REGION)
    out = []
    for page in logs.get_paginator("filter_log_events").paginate(
            logGroupName=f"/aws/lambda/{PREFIX}-{function}", startTime=start_ms, filterPattern='"REPORT RequestId"'):
        for event in page["events"]:
            parts = dict(part.split(": ", 1) for part in event["message"].strip().split("\t")[1:] if ": " in part)
            out.append({"at": event["timestamp"], "seconds": float(parts["Duration"].split()[0]) / 1000})
    return out


def nearest(items: list[dict], at_ms: int, window_ms: int = 600_000) -> dict | None:
    close = [item for item in items if abs(item["at"] - at_ms) <= window_ms]
    return min(close, key=lambda item: abs(item["at"] - at_ms)) if close else None


def main() -> None:
    snaps = snapshots()
    first_ms = int(datetime.fromisoformat(snaps[0]["saved_at"].replace("Z", "+00:00")).timestamp() * 1000) - 3_600_000
    discovery, imports = reports("discovery", first_ms), reports("import", first_ms)
    measured = {json.loads(path.read_text())["started_at"]: json.loads(path.read_text()) for path in sorted(PULLS.glob("*.json"))}
    rows = []
    for snap in snaps:
        saved_ms = int(datetime.fromisoformat(snap["saved_at"].replace("Z", "+00:00")).timestamp() * 1000)
        by_source = Counter(job["source"] for job in snap["jobs"])
        dup = duplicates(snap["jobs"])
        disc, imp = nearest(discovery, saved_ms), nearest(imports, saved_ms)
        record = next((m for m in measured.values() if abs(int(datetime.fromisoformat(m["started_at"].replace("Z", "+00:00"))
                                                               .timestamp() * 1000) - saved_ms) < 600_000), None)
        imported = (record or {}).get("result", {}).get("import") or {}
        rows.append({"saved_at": snap["saved_at"], "fetched": len(snap["jobs"]), "by_source": dict(by_source),
                     "cross_source_duplicates": dict(dup), "failures": snap.get("failures") or [],
                     "truncated": snap.get("truncated_boards") or [],
                     "discovery_seconds": disc and round(disc["seconds"], 1), "import_seconds": imp and round(imp["seconds"], 1),
                     "new": imported.get("new"), "already_stored": (imported.get("updated", 0) + imported.get("unchanged", 0)) if imported else None,
                     "deferred": imported.get("deferred"),
                     "to_embedding_finished_s": (record or {}).get("seconds", {}).get("to_embedding_finished")})
    failures = Counter(f"{failure['source']}:{failure.get('board')} {failure['kind']}" for row in rows for failure in row["failures"])
    out_dir = ROOT / "eval" / "results" / f"b4-pipeline-{datetime.now(timezone.utc):%Y%m%d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps({"pulls": rows, "failures": failures}, indent=2))

    dash = lambda value: "–" if value is None else str(value)   # noqa: E731
    lines = ["# B4 job pipeline: every pull on staging", "",
             "| Pull (UTC) | Fetched | " + " | ".join(SOURCES) + " | Cross-source duplicates | New / already stored / deferred | "
             "Discovery s | Import s | To embedded s | Failures | Truncated searches |",
             "|---|---|" + "---|" * len(SOURCES) + "---|---|---|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['saved_at'][:16]} | {row['fetched']} | " + " | ".join(str(row["by_source"].get(s, 0)) for s in SOURCES)
                     + f" | {sum(row['cross_source_duplicates'].values())} | {dash(row['new'])} / {dash(row['already_stored'])} / "
                     f"{dash(row['deferred'])} | {dash(row['discovery_seconds'])} | {dash(row['import_seconds'])} | "
                     f"{dash(row['to_embedding_finished_s'])} | {len(row['failures'])} | {len(row['truncated'])} |")
    lines += ["", f"Pulls: {len(rows)}. Failures by kind: {dict(failures) or 'none'}.",
              "Truncated searches (more postings than one pull reads): "
              + ", ".join(sorted({board for row in rows for board in row["truncated"]})) + ".",
              "New / already stored / deferred are known only for pulls run with eval/b4_pull.py (the workflow writes them to "
              "its job summary, which is not kept)."]
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
