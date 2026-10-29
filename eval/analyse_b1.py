"""Summarise a B1 responsiveness run: client-side (Locust) and server-side (API Gateway access log) percentiles.

Usage (from the repository root, evaluation virtualenv, with an operator SSO session for the access logs):
    AWS_PROFILE=<operator profile> python eval/analyse_b1.py eval/results/b1-baseline-20261025

Reads <dir>/b1_stats.csv and the measured window from <dir>/config.txt, fetches the access-log lines for that
window from /aws/apigateway/jobhunter-staging, and writes <dir>/summary.md and <dir>/summary.json.

Server-side "gateway" latency is API Gateway's responseLatency (request received to response sent); "lambda" is
integrationLatency (time in the API function). The access log has no user field, so any other staging traffic in
the window is included; the window is reported so this can be checked.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3

LOG_GROUP, REGION = "/aws/apigateway/jobhunter-staging", "ap-southeast-1"
BROWSE_TARGET_MS, RANKING_TARGET_MS = 500, 2000
# Group per the evaluation plan. All jobs is the default listing (browse) even though it ranks by keywords.
RANKING = {"/recommendations/for-you", "/resume-builds/suggest", "/documents/{id}/preview.pdf"}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, round(p / 100 * len(ordered) + 0.5) - 1))   # nearest-rank
    return ordered[rank]


def normalise(path: str) -> str:
    path = path.removeprefix("/v1")
    return UUID.sub("{id}", path)


def window(directory: Path) -> tuple[int, int]:
    text = (directory / "config.txt").read_text()
    stamps = [re.search(rf"measured run {label}: (\S+)", text).group(1) for label in ("start", "end")]
    return tuple(int(datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()) * 1000 for s in stamps)


def access_log(start_ms: int, end_ms: int) -> list[dict]:
    # boto3's paginator, not the CLI: `aws logs filter-log-events --query` silently dropped ~1% of lines here.
    pages = boto3.client("logs", region_name=REGION).get_paginator("filter_log_events").paginate(
        logGroupName=LOG_GROUP, startTime=start_ms, endTime=end_ms)
    return [json.loads(event["message"]) for page in pages for event in page["events"]]


def main(directory: Path) -> None:
    client = {}
    with open(directory / "b1_stats.csv") as handle:
        for row in csv.DictReader(handle):
            if row["Name"] == "Aggregated":
                continue
            client[row["Name"]] = {"requests": int(row["Request Count"]), "failures": int(row["Failure Count"]),
                                   "p50": float(row["50%"]), "p95": float(row["95%"]), "p99": float(row["99%"])}
    start_ms, end_ms = window(directory)
    server: dict[str, dict[str, list[float]]] = {}
    statuses: dict[str, int] = {}
    for line in access_log(start_ms, end_ms):
        name = normalise(line.get("path", ""))
        statuses[line.get("status", "?")] = statuses.get(line.get("status", "?"), 0) + 1
        bucket = server.setdefault(name, {"gateway": [], "lambda": []})
        for field, key in (("latencyMs", "gateway"), ("integrationMs", "lambda")):
            if str(line.get(field, "-")).isdigit():
                bucket[key].append(float(line[field]))

    rows = []
    for name in sorted(client):
        target = RANKING_TARGET_MS if name in RANKING else BROWSE_TARGET_MS
        side = server.get(name, {"gateway": [], "lambda": []})
        row = {"endpoint": name, "group": "ranking" if name in RANKING else "browse", "target_p95_ms": target,
               "client": client[name],
               "server_gateway": {f"p{p}": percentile(side["gateway"], p) for p in (50, 95, 99)} | {"n": len(side["gateway"])},
               "server_lambda": {f"p{p}": percentile(side["lambda"], p) for p in (50, 95, 99)}}
        row["meets_target"] = client[name]["p95"] <= target
        rows.append(row)

    summary = {"window_utc": [datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                              for t in (start_ms, end_ms)],
               "access_log_status_counts": statuses, "endpoints": rows}
    (directory / "summary.json").write_text(json.dumps(summary, indent=2))

    def ms(value):
        return "–" if value is None else f"{value:.0f}"

    lines = [f"# B1 responsiveness baseline ({summary['window_utc'][0][:16]} – {summary['window_utc'][1][11:16]} UTC)", "",
             "One warm user, 0.1 s between requests. Client = Locust on the operator laptop (includes network). "
             "Server = API Gateway access log (gateway total / time in the API function). Milliseconds.", "",
             "| Endpoint | Group | Target P95 | Requests | Failures | Client P50 / P95 / P99 | Server P50 / P95 / P99 | Lambda P50 / P95 | Meets target |",
             "|---|---|---|---|---|---|---|---|---|"]
    for row in rows:
        c, g, f = row["client"], row["server_gateway"], row["server_lambda"]
        lines.append(f"| `{row['endpoint']}` | {row['group']} | {row['target_p95_ms']} | {c['requests']} | {c['failures']} | "
                     f"{ms(c['p50'])} / {ms(c['p95'])} / {ms(c['p99'])} | {ms(g['p50'])} / {ms(g['p95'])} / {ms(g['p99'])} | "
                     f"{ms(f['p50'])} / {ms(f['p95'])} | {'yes' if row['meets_target'] else '**no**'} |")
    lines += ["", f"Access-log status counts in the window: {statuses}."]
    (directory / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
