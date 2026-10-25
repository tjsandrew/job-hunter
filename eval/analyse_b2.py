"""Summarise a B2 run: client timings from runs.json joined with the LLM worker's per-task log lines.

Usage (from the repository root, evaluation virtualenv, with an operator SSO session for the worker log):
    AWS_PROFILE=<operator profile> python eval/analyse_b2.py eval/results/b2-ai-tasks-<stamp>

A fit analysis is joined by its request id (the analysis id). A cover letter or rewrite has a request id the client
never sees, so it is joined to the first unused worker line of the same task logged after it was sent (the runner
sends one request at a time, so this is unambiguous).

Completion time is split into: waiting for the worker (S3 event to worker start), the model calls, the rest of the
worker (reading the request, writing the result) and what remains (the API's polling delay and request overheads).
Writes summary.md and summary.json next to runs.json.
"""
from __future__ import annotations

import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3

LOG_GROUP, REGION = "/aws/lambda/jobhunter-staging-llm", "ap-southeast-1"
ACCEPT_TARGET_S, COMPLETE_TARGET_S = 0.2, 30.0
TASK_NAMES = {"fit": "Fit analysis", "cover_letter": "AI cover letter", "tailor": "AI resume rewrite"}


def epoch_ms(stamp: str) -> int:
    return int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() * 1000)


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, round(p / 100 * len(ordered) + 0.5) - 1))]   # nearest-rank


def worker_lines(start_ms: int, end_ms: int) -> list[dict]:
    pages = boto3.client("logs", region_name=REGION).get_paginator("filter_log_events").paginate(
        logGroupName=LOG_GROUP, startTime=start_ms, endTime=end_ms, filterPattern='"llm_task"')
    lines = []
    for page in pages:
        for event in page["events"]:
            text = event["message"]
            try:
                line = json.loads(text[text.index("{"):])      # the Lambda runtime prefixes level, time and request id
            except ValueError:
                continue
            if line.get("event") == "llm_task":
                lines.append({**line, "logged_ms": event["timestamp"]})
    return sorted(lines, key=lambda line: line["logged_ms"])


def join(runs: list[dict], lines: list[dict]) -> None:
    by_id = {line["request_id"]: line for line in lines}
    used = set()
    for run in runs:
        if "sent_at" not in run:
            continue
        line = by_id.get(run.get("request_id")) if run["task"] == "fit" else None
        if line is None:
            sent = epoch_ms(run["sent_at"])
            line = next((candidate for candidate in lines if candidate["task"] == run["task"]
                         and candidate["request_id"] not in used and candidate["logged_ms"] >= sent), None)
        if line is not None:
            used.add(line["request_id"])
            run["worker"] = {key: line.get(key) for key in ("request_id", "outcome", "waited_ms", "task_ms", "model",
                                                            "model_calls", "model_ms", "prompt_tokens", "output_tokens")}


def seconds(value) -> str:
    return "–" if value is None else f"{value:.1f}"


def main(directory: Path) -> None:
    record = json.loads((directory / "runs.json").read_text())
    runs = record["runs"]
    lines = worker_lines(epoch_ms(record["started_at"]) - 60_000, epoch_ms(record["finished_at"]) + 180_000)
    join(runs, lines)
    tasks = {}
    for task in TASK_NAMES:
        mine = [run for run in runs if run["task"] == task]
        done = [run for run in mine if run.get("outcome") == "ready" and run.get("complete_s") is not None]
        joined = [run for run in done if run.get("worker")]
        complete = [run["complete_s"] for run in done]
        part = {key: [run["worker"][key] / 1000 for run in joined if run["worker"].get(key) is not None]
                for key in ("waited_ms", "model_ms", "task_ms")}
        worker_rest = [(run["worker"]["task_ms"] - run["worker"]["model_ms"]) / 1000 for run in joined]
        remainder = [run["complete_s"] - (run["worker"]["waited_ms"] or 0) / 1000 - run["worker"]["task_ms"] / 1000
                     for run in joined if run["worker"].get("task_ms") is not None]
        tasks[task] = {
            "runs": len(mine), "ready": len(done),
            "failures": sorted({str(run.get("error") or run.get("outcome")) for run in mine if run not in done}),
            "accept_p50_s": percentile([run["accept_s"] for run in mine if "accept_s" in run], 50),
            "accept_p95_s": percentile([run["accept_s"] for run in mine if "accept_s" in run], 95),
            "complete_p50_s": percentile(complete, 50), "complete_p95_s": percentile(complete, 95),
            "complete_max_s": max(complete) if complete else None,
            "within_target": sum(value <= COMPLETE_TARGET_S for value in complete),
            "mean_waited_s": statistics.fmean(part["waited_ms"]) if part["waited_ms"] else None,
            "mean_model_s": statistics.fmean(part["model_ms"]) if part["model_ms"] else None,
            "mean_worker_rest_s": statistics.fmean(worker_rest) if worker_rest else None,
            "mean_remainder_s": statistics.fmean(remainder) if remainder else None,
            "mean_model_calls": statistics.fmean([run["worker"]["model_calls"] for run in joined]) if joined else None,
            "mean_prompt_tokens": statistics.fmean([run["worker"]["prompt_tokens"] for run in joined]) if joined else None,
            "mean_output_tokens": statistics.fmean([run["worker"]["output_tokens"] for run in joined]) if joined else None,
            "joined_to_worker_log": len(joined),
        }
    summary = {"window_utc": [record["started_at"], record["finished_at"]], "model": next(
        (line.get("model") for line in lines if line.get("model")), None), "tasks": tasks, "runs": runs}
    (directory / "summary.json").write_text(json.dumps(summary, indent=2))

    out = [f"# B2 AI task timings ({record['started_at'][:16]} – {record['finished_at'][11:16]} UTC)", "",
           f"Model: `{summary['model']}`. One request at a time; fit analysis polled every second. Seconds.", "",
           "| Task | Ready / runs | Accept P50 / P95 | Complete P50 / P95 / max | Within 30 s | Failures |",
           "|---|---|---|---|---|---|"]
    for task, row in tasks.items():
        accept = (f"{row['accept_p50_s'] * 1000:.0f} / {row['accept_p95_s'] * 1000:.0f} ms"
                  if row["accept_p50_s"] is not None else "– (answered in the request)")
        out.append(f"| {TASK_NAMES[task]} | {row['ready']} / {row['runs']} | {accept} | {seconds(row['complete_p50_s'])} / "
                   f"{seconds(row['complete_p95_s'])} / {seconds(row['complete_max_s'])} | {row['within_target']} / "
                   f"{row['ready']} | {', '.join(row['failures']) or 'none'} |")
    out += ["", "Where the time goes (means over runs joined to the worker log):", "",
            "| Task | Waiting for worker | Model calls | Rest of worker | Polling and API | Model calls per run | "
            "Prompt / output tokens per run |", "|---|---|---|---|---|---|---|"]
    for task, row in tasks.items():
        tokens = (f"{row['mean_prompt_tokens']:.0f} / {row['mean_output_tokens']:.0f}"
                  if row["mean_prompt_tokens"] is not None else "–")
        calls = f"{row['mean_model_calls']:.1f}" if row["mean_model_calls"] is not None else "–"
        out.append(f"| {TASK_NAMES[task]} | {seconds(row['mean_waited_s'])} | {seconds(row['mean_model_s'])} | "
                   f"{seconds(row['mean_worker_rest_s'])} | {seconds(row['mean_remainder_s'])} | {calls} | {tokens} |")
    (directory / "summary.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
