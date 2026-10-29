"""B2: time the three AI tasks on staging (fit analysis, AI cover letter, AI resume rewrite).

For each chosen job, one account runs, one after another:
* fit analysis: POST /jobs/{id}/fit-analysis (202), then GET /fit-analyses/{id} every second until ready or failed;
* cover letter: POST /jobs/{id}/cover-letter (mode "write"), answered inside the request (the API waits up to 25 s);
* resume rewrite: a resume is built for the job from the profile bank (POST /resume-builds/suggest, then
  /documents/from-bank, as the web app does), then POST /documents/{id}/tailor with mode "ai".

The allowance is one slot per user and job per month, shared by all three tasks, so each job costs one of the
account's five free uses. Accounts jh-eval-01..05 take JOBS_PER_ACCOUNT jobs each; jh-eval-06 is kept spare.
Jobs come from each account's For you list (distinct across accounts, never one the account already used).

Writes eval/results/b2-ai-tasks-<UTC time>/runs.json (no tokens, no generated text). The worker's own timings and
token counts are joined in afterwards from its log (see analyse_b2.py). Documents it creates are deleted at the end.

    python eval/b2_ai_tasks.py            # 5 accounts x 3 jobs = 15 runs of each task

Re-running some tasks on the jobs of an earlier run (free: those jobs already hold this month's slot):
    B2_TASKS=tailor B2_SAME_JOBS_AS=eval/results/b2-ai-tasks-<stamp>/runs.json python eval/b2_ai_tasks.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cognito_tokens as ct  # noqa: E402

ACCOUNTS = [f"jh-eval-0{n}@example.com" for n in range(1, 6)]
JOBS_PER_ACCOUNT = int(os.environ.get("B2_JOBS_PER_ACCOUNT", "3"))
TASKS = os.environ.get("B2_TASKS", "fit,cover_letter,tailor").split(",")
SAME_JOBS_AS = os.environ.get("B2_SAME_JOBS_AS")
POLL_SECONDS, FIT_GIVE_UP_SECONDS = 1.0, 120
RESULTS = Path(__file__).resolve().parent / "results"


def call(token: str, method: str, path: str, body=None, timeout: float = 60):
    """(status, JSON body or None, seconds). Never raises for an HTTP error status."""
    request = Request(ct.API_BASE + path, method=method, data=None if body is None else json.dumps(body).encode(),
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            raw, status = response.read(), response.status
    except HTTPError as exc:
        raw, status = exc.read(), exc.code
    elapsed = time.perf_counter() - started
    try:
        payload = json.loads(raw) if raw[:1] in (b"{", b"[") else None
    except ValueError:
        payload = None
    return status, payload, elapsed


def error_code(payload) -> str | None:
    detail = (payload or {}).get("detail") if isinstance(payload, dict) else None
    return detail.get("code") if isinstance(detail, dict) else None


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"


def pick_jobs(token: str, taken: set[str], count: int) -> list[dict]:
    status, payload, _ = call(token, "GET", "/recommendations/for-you?limit=50")
    if status != 200:
        raise RuntimeError(f"For you failed: {status}")
    used = {row["job_id"] for row in (call(token, "GET", "/fit-analyses")[1] or {}).get("items", [])}
    chosen = []
    for item in payload.get("items", []):
        job = item.get("job") or item
        job_id = str(job["id"])
        if job_id in taken or job_id in used:
            continue
        status, detail, _ = call(token, "GET", f"/jobs/{job_id}")
        if status == 200 and len((detail.get("description") or "").strip()) >= 200:   # enough text to find requirements
            chosen.append({"id": job_id, "title": detail.get("title"), "description_chars": len(detail["description"])})
            taken.add(job_id)
        if len(chosen) == count:
            break
    return chosen


def run_fit(token: str, job_id: str) -> dict:
    sent = utc_now()
    status, payload, accept = call(token, "POST", f"/jobs/{job_id}/fit-analysis", {})
    run = {"task": "fit", "sent_at": sent, "status": status, "accept_s": round(accept, 3), "error": error_code(payload)}
    if status != 202:
        return run
    run["request_id"] = payload["id"]
    started, polls = time.perf_counter() - accept, 0
    while time.perf_counter() - started < FIT_GIVE_UP_SECONDS:
        time.sleep(POLL_SECONDS)
        polls += 1
        _, item, _ = call(token, "GET", f"/fit-analyses/{payload['id']}")
        if item and item["status"] != "pending":
            run.update(outcome=item["status"], error=item.get("error_code"), complete_s=round(time.perf_counter() - started, 3),
                       polls=polls, requirements=len(((item.get("result") or {}).get("requirements")) or []))
            return run
    run.update(outcome="gave_up", complete_s=None, polls=polls)
    return run


def run_letter(token: str, job_id: str, created: list[str]) -> dict:
    sent = utc_now()
    status, payload, seconds = call(token, "POST", f"/jobs/{job_id}/cover-letter", {"mode": "write", "tone": "formal"})
    run = {"task": "cover_letter", "sent_at": sent, "status": status, "complete_s": round(seconds, 3),
           "outcome": "ready" if status == 201 else "failed", "error": error_code(payload)}
    if status == 201:
        created.append(payload["document"]["id"])
        run["paragraphs"] = len(payload["document"]["content"].get("paragraphs") or [])
    return run


def run_rewrite(token: str, job_id: str, created: list[str]) -> dict:
    status, suggestion, _ = call(token, "POST", "/resume-builds/suggest", {"job_id": job_id})
    if status != 200:
        return {"task": "tailor", "outcome": "failed", "status": status, "error": f"suggest: {error_code(suggestion)}"}
    plan = {**suggestion["plan"], "title": "B2 base resume (fictional)", "job_id": job_id}
    status, base, _ = call(token, "POST", "/documents/from-bank", plan)
    if status != 201:
        return {"task": "tailor", "outcome": "failed", "status": status, "error": f"from-bank: {error_code(base)}"}
    created.append(base["id"])
    bullets = sum(len(entry.get("bullets") or []) for section in base["content"].get("sections", [])
                  for entry in section.get("entries", []))
    sent = utc_now()
    status, payload, seconds = call(token, "POST", f"/documents/{base['id']}/tailor", {"job_id": job_id, "mode": "ai"})
    ai = (payload or {}).get("ai") or {}
    run = {"task": "tailor", "sent_at": sent, "status": status, "complete_s": round(seconds, 3), "bullets": bullets,
           "outcome": "ready" if status == 201 and ai.get("status") in ("applied", "unchanged") else "failed",
           "ai_status": ai.get("status"), "changed": ai.get("changed"), "error": error_code(payload) or ai.get("reason")}
    if status == 201:
        created.append(payload["document"]["id"])
    return run


def earlier_jobs(path: str) -> dict[str, list[dict]]:
    """Each account's jobs from an earlier runs.json, in their original order."""
    jobs: dict[str, list[dict]] = {}
    for run in json.loads(Path(path).read_text())["runs"]:
        mine = jobs.setdefault(run["account"], [])
        if run["job_id"] not in [job["id"] for job in mine]:
            mine.append({"id": run["job_id"], "title": run["job_title"], "description_chars": run["description_chars"]})
    return jobs


def main() -> int:
    accounts = ct.load_accounts()
    reused = earlier_jobs(SAME_JOBS_AS) if SAME_JOBS_AS else None
    out_dir = RESULTS / f"b2-ai-tasks-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    out_dir.mkdir(parents=True)
    runs, taken = [], set()
    record = {"started_at": utc_now(), "api": ct.API_BASE, "jobs_per_account": JOBS_PER_ACCOUNT, "tasks": TASKS,
              "same_jobs_as": SAME_JOBS_AS, "runs": runs}
    for email in ACCOUNTS:
        token = ct.login(email, accounts[email]["password"])["access_token"]
        _, me, _ = call(token, "GET", "/me")
        allowance = (me or {}).get("allowance") or {}
        print(f"{email}: {allowance.get('used')}/{allowance.get('limit')} AI uses spent this month", flush=True)
        created: list[str] = []
        jobs = reused.get(email, []) if reused is not None else pick_jobs(token, taken, JOBS_PER_ACCOUNT)
        for job in jobs:
            runners = {"fit": lambda: run_fit(token, job["id"]), "cover_letter": lambda: run_letter(token, job["id"], created),
                       "tailor": lambda: run_rewrite(token, job["id"], created)}
            for name in TASKS:
                run = {"account": email, "job_id": job["id"], "job_title": job["title"],
                       "description_chars": job["description_chars"], **runners[name]()}
                runs.append(run)
                (out_dir / "runs.json").write_text(json.dumps(record, indent=2))
                print(f"  {run['task']:12} {run.get('outcome')!s:8} accept={run.get('accept_s')} "
                      f"complete={run.get('complete_s')} error={run.get('error')}  {job['title'][:40]}", flush=True)
        for document_id in created:
            call(token, "DELETE", f"/documents/{document_id}")
    record["finished_at"] = utc_now()
    (out_dir / "runs.json").write_text(json.dumps(record, indent=2))
    print(f"\n{len(runs)} runs; results in {out_dir.relative_to(Path.cwd())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
