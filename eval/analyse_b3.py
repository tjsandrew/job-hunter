"""Summarise a B3 step-load run per step: server throughput, latency, caps vs errors, Lambda and Aurora metrics.

Usage (from the repository root, evaluation virtualenv, with an operator SSO session):
    AWS_PROFILE=<operator profile> python eval/analyse_b3.py eval/results/b3-run1-<date>

Step windows come from Locust's per-second history (<dir>/b3_stats_history.csv): each step is the time the user
count sat at that step's value, and only its last STEADY_SECONDS are analysed (the first minute is ramp-up and
settling). Server figures come from the API Gateway access log; 429 is the gateway's deliberate rate cap, 5xx are
errors (including the API function being throttled at its reserved concurrency). CloudWatch metrics are per minute.
Writes summary.md and summary.json.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import boto3

REGION = "ap-southeast-1"
LOG_GROUP, FUNCTION, CLUSTER = "/aws/apigateway/jobhunter-staging", "jobhunter-staging-api", "jobhunter-staging"
STEADY_SECONDS = 300
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
KEY_ENDPOINTS = ["GET /recommendations", "GET /recommendations/for-you", "GET /jobs/{id}", "PUT /jobs/{id}/review", "GET /me"]


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, round(p / 100 * len(ordered) + 0.5) - 1))]   # nearest-rank


def steps(directory: Path) -> list[dict]:
    """[{users, start, end}] in epoch seconds, from the aggregated rows of the per-second history."""
    seen: dict[int, list[int]] = defaultdict(list)
    with open(directory / "b3_stats_history.csv") as handle:
        for row in csv.DictReader(handle):
            if row["Name"] == "Aggregated" and int(row["User Count"]) > 0:
                seen[int(row["User Count"])].append(int(row["Timestamp"]))
    targets = [users for users, stamps in seen.items() if len(stamps) >= STEADY_SECONDS]   # skip counts passed while ramping
    return [{"users": users, "start": max(seen[users]) - STEADY_SECONDS, "end": max(seen[users])} for users in sorted(targets)]


def access_log(start: int, end: int) -> list[dict]:
    pages = boto3.client("logs", region_name=REGION).get_paginator("filter_log_events").paginate(
        logGroupName=LOG_GROUP, startTime=start * 1000, endTime=end * 1000)
    return [json.loads(event["message"]) for page in pages for event in page["events"]]


def metric(namespace: str, name: str, dimension: tuple[str, str], stat: str, start: int, end: int) -> list[float]:
    """Per-minute values for the whole minutes inside [start, end): a partly covered minute would mix in the next step."""
    first, last = -(-start // 60) * 60, end // 60 * 60
    response = boto3.client("cloudwatch", region_name=REGION).get_metric_statistics(
        Namespace=namespace, MetricName=name, Dimensions=[{"Name": dimension[0], "Value": dimension[1]}],
        StartTime=datetime.fromtimestamp(first, timezone.utc), EndTime=datetime.fromtimestamp(last, timezone.utc),
        Period=60, Statistics=[stat])
    return [point[stat] for point in sorted(response["Datapoints"], key=lambda point: point["Timestamp"])]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def endpoint(line: dict) -> str:
    return f"{line.get('method')} {UUID.sub('{id}', line.get('path', '').removeprefix('/v1'))}"


def summarise(step: dict) -> dict:
    lines = access_log(step["start"], step["end"])
    statuses = Counter(str(line.get("status")) for line in lines)
    ok = [line for line in lines if str(line.get("status", "")).startswith("2")]
    latency = [float(line["latencyMs"]) for line in ok if str(line.get("latencyMs", "")).isdigit()]
    per_endpoint = defaultdict(list)
    for line in ok:
        if str(line.get("latencyMs", "")).isdigit():
            per_endpoint[endpoint(line)].append(float(line["latencyMs"]))
    seconds = step["end"] - step["start"]
    window = (step["start"], step["end"])
    lambda_dim, db_dim = ("FunctionName", FUNCTION), ("DBClusterIdentifier", CLUSTER)
    return {
        **step, "seconds": seconds, "requests": len(lines),
        "throughput_rps": len(lines) / seconds, "ok_rps": len(ok) / seconds,
        "status_counts": dict(sorted(statuses.items())),
        "throttled_429": statuses.get("429", 0),
        "errors_5xx": sum(count for status, count in statuses.items() if status.startswith("5")),
        "ok_p50_ms": percentile(latency, 50), "ok_p95_ms": percentile(latency, 95), "ok_p99_ms": percentile(latency, 99),
        "endpoint_p95_ms": {name: percentile(per_endpoint[name], 95) for name in KEY_ENDPOINTS},
        "endpoint_ok_counts": {name: len(per_endpoint[name]) for name in KEY_ENDPOINTS},
        "lambda_concurrency_max": max(metric("AWS/Lambda", "ConcurrentExecutions", lambda_dim, "Maximum", *window), default=None),
        "lambda_throttles": sum(metric("AWS/Lambda", "Throttles", lambda_dim, "Sum", *window)),
        "lambda_errors": sum(metric("AWS/Lambda", "Errors", lambda_dim, "Sum", *window)),
        "aurora_acu_max": max(metric("AWS/RDS", "ServerlessDatabaseCapacity", db_dim, "Maximum", *window), default=None),
        "aurora_connections_max": max(metric("AWS/RDS", "DatabaseConnections", db_dim, "Maximum", *window), default=None),
        "aurora_cpu_max": max(metric("AWS/RDS", "CPUUtilization", db_dim, "Maximum", *window), default=None),
        "aurora_cpu_avg": _mean(metric("AWS/RDS", "CPUUtilization", db_dim, "Average", *window)),
        "lambda_duration_avg_ms": _mean(metric("AWS/Lambda", "Duration", lambda_dim, "Average", *window)),
    }


def number(value, digits: int = 0) -> str:
    return "–" if value is None else f"{value:,.{digits}f}"


def main(directory: Path) -> None:
    rows = [summarise(step) for step in steps(directory)]
    (directory / "summary.json").write_text(json.dumps({"steady_seconds": STEADY_SECONDS, "steps": rows}, indent=2))
    stamp = lambda epoch: datetime.fromtimestamp(epoch, timezone.utc).strftime("%H:%M:%S")   # noqa: E731
    out = ["# B3 step load: per step (server side)", "",
           f"Last {STEADY_SECONDS} s of each step. Latency is API Gateway's, for successful (2xx) requests, in ms. "
           "429 = the gateway's deliberate rate cap; 5xx = errors (includes the API function hitting its reserved concurrency).", "",
           "| Users | Window (UTC) | Requests/s | 2xx/s | P50 / P95 / P99 | 429 | 5xx | Lambda conc. max | Lambda throttles | "
           "Aurora ACU max | DB conn. max | DB CPU avg / max |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for row in rows:
        out.append(f"| {row['users']} | {stamp(row['start'])}–{stamp(row['end'])} | {number(row['throughput_rps'], 1)} | "
                   f"{number(row['ok_rps'], 1)} | {number(row['ok_p50_ms'])} / {number(row['ok_p95_ms'])} / {number(row['ok_p99_ms'])} | "
                   f"{row['throttled_429']} | {row['errors_5xx']} | {number(row['lambda_concurrency_max'])} | "
                   f"{number(row['lambda_throttles'])} | {number(row['aurora_acu_max'], 2)} | {number(row['aurora_connections_max'])} | "
                   f"{number(row['aurora_cpu_avg'], 0)} / {number(row['aurora_cpu_max'], 0)}% |")
    out += ["", "P95 by endpoint (2xx only, ms; count in brackets):", "",
            "| Users | " + " | ".join(f"`{name}`" for name in KEY_ENDPOINTS) + " |", "|---|" + "---|" * len(KEY_ENDPOINTS)]
    for row in rows:
        out.append(f"| {row['users']} | " + " | ".join(f"{number(row['endpoint_p95_ms'][name])} ({row['endpoint_ok_counts'][name]})"
                                                    for name in KEY_ENDPOINTS) + " |")
    out += ["", "Status counts per step: " + "; ".join(f"{row['users']} users {row['status_counts']}" for row in rows) + "."]
    (directory / "summary.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
